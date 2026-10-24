"""Measured, coupled ISP response and native-table fitting (offline research).

The inverse map is identified from zero/axis/ramp captures, rather than an
assumed gamma or a DCP renderer. The forward map must predict a retained
camera table before fitting a new look. Neither a chart fit nor its prediction
establishes new-scene camera accuracy.
"""
import itertools
import numpy as np
from scipy.interpolate import NdBSpline, RBFInterpolator
from scipy.optimize import least_squares, lsq_linear
from scipy.sparse import coo_matrix, eye, vstack
from . import measuredfit, native


def spline_design(rgb, knots):
    n = len(knots) - 4
    matrix = NdBSpline.design_matrix(
        np.ascontiguousarray(rgb, dtype=float), (knots,) * 3, (3,) * 3,
        extrapolate=True).tocsr()
    # SciPy omits trailing unvisited basis columns. Every capture must use
    # the same complete basis, including captures far from the gamut edge.
    matrix.resize((len(rgb), n ** 3))
    return matrix


def native_curvature():
    """Second differences; affine native correction fields have zero cost."""
    rows, columns, values, row = [], [], [], 0
    for position in itertools.product(range(5), range(9), range(9)):
        for axis, size in enumerate((5, 9, 9)):
            if position[axis] in (0, size - 1):
                continue
            for displacement, weight in ((-1, 1), (0, -2), (1, 1)):
                at = list(position)
                at[axis] += displacement
                node = at[0] * 81 + at[1] * 9 + at[2]
                for channel in range(3):
                    rows.append(row + channel)
                    columns.append(node * 3 + channel)
                    values.append(weight * (size - 1) ** 2)
            row += 3
    return coo_matrix((values, (rows, columns)), shape=(row, 1215)).tocsr()


class Response:
    def __init__(self, knots, inverse, scale, forward_coordinates, forward_rgb):
        self.knots = np.asarray(knots)
        self.inverse = np.asarray(inverse)
        self.scale = np.asarray(scale)
        self.forward = RBFInterpolator(
            forward_coordinates, forward_rgb, neighbors=min(100, len(forward_rgb)),
            smoothing=.001, kernel='thin_plate_spline')

    def coordinates(self, rgb):
        return spline_design(rgb, self.knots) @ self.inverse

    def render(self, coordinates, corrections):
        return np.clip(self.forward(coordinates + corrections * self.scale), 0, 1)

    def predict_table(self, coordinates, coefficients):
        ids, weights = measuredfit.interpolation(np.clip(coordinates, 0, 1))
        corrections = (np.asarray(coefficients)[ids] * weights[..., None]).sum(1)
        return self.render(coordinates, corrections)


def metrics(actual, target):
    error = np.abs(np.asarray(actual) - target) * 255
    return {'RGB_MAE_8bit': float(error.mean()),
            'RGB_P95_8bit': float(np.percentile(error, 95))}


def solve(response, coordinates, target_rgb, *, smooth, bounded=True,
          refine=False, max_evaluations=25, initial_coefficients=None):
    """Joint solve, with an optional refinement against predicted encoded RGB.

    No per-patch target values become table nodes directly: all 1,215 native
    coefficients share one interpolated field. Float coefficients stay float
    until the caller explicitly quantizes the final candidate.
    """
    coordinates = np.asarray(coordinates)
    field_coordinates = np.clip(coordinates, 0, 1)
    regularizer = vstack([native_curvature() * np.sqrt(smooth), eye(1215) * 1e-7],
                        format='csr')
    bounds = (-64, 63) if bounded else (-np.inf, np.inf)
    if initial_coefficients is None:
        target_coordinates = response.coordinates(target_rgb)
        local_response = np.tile(np.diag(response.scale), (len(coordinates), 1, 1))
        matrix = measuredfit.design(field_coordinates, local_response)
        system = vstack([matrix, regularizer], format='csr')
        rhs = np.r_[(target_coordinates - coordinates).ravel(),
                    np.zeros(regularizer.shape[0])]
        initial = lsq_linear(system, rhs, bounds=bounds, tol=1e-8,
                             lsmr_tol=1e-8, max_iter=100)
        # Hitting the seed budget still leaves an approximation that the full
        # fit can improve. Numerical failures remain errors.
        if initial.status < 0 or not np.isfinite(initial.x).all():
            raise ValueError('Coupled native seed failed: ' + initial.message)
        coefficients = initial.x
    else:
        coefficients = np.asarray(initial_coefficients, dtype=float).reshape(1215)
    report = {'bounded': bounded, 'curvature_strength': smooth,
              'RGB_refined': False, 'new_scene_camera_verified': False,
              'initialization': 'inverse response' if initial_coefficients is None else 'supplied field'}
    if initial_coefficients is None:
        report['seed_optimizer'] = dict(converged=bool(initial.success),
            status=int(initial.status), iterations=int(initial.nit), message=str(initial.message))
        if initial.status == 0:
            print('初始拟合达到迭代预算，保留当前近似值继续优化；不会中断转换。', flush=True)
    if refine:
        ids, weights = measuredfit.interpolation(field_coordinates)
        cache = {}

        def evaluate(vector):
            if 'vector' not in cache or not np.array_equal(vector, cache['vector']):
                correction = (vector.reshape(405, 3)[ids] * weights[..., None]).sum(1)
                at = coordinates + correction * response.scale
                cache.update(vector=vector.copy(), at=at, rgb=response.forward(at))
            return cache['at'], cache['rgb']

        def residual(vector):
            _, rgb = evaluate(vector)
            return np.r_[(np.clip(rgb, 0, 1) - target_rgb).ravel(), regularizer @ vector]

        def jacobian(vector):
            at, rgb = evaluate(vector)
            delta = .25  # native coefficient units, not encoded RGB units
            derivative = np.empty((len(coordinates), 3, 3))
            for axis in range(3):
                step = np.eye(3)[axis] * response.scale[axis] * delta
                derivative[:, axis, :] = (response.forward(at + step) -
                                          response.forward(at - step)) / (2 * delta)
            derivative *= ((rgb > 0) & (rgb < 1))[:, None, :]
            return vstack([measuredfit.design(field_coordinates, derivative), regularizer],
                          format='csr')

        result = least_squares(residual, coefficients, jac=jacobian, bounds=bounds,
                               method='trf', tr_solver='lsmr', max_nfev=max_evaluations,
                               ftol=1e-5, xtol=1e-5, gtol=1e-6)
        # Keep the seed if a limited refinement does not improve its objective.
        if np.linalg.norm(result.fun) < np.linalg.norm(residual(coefficients)):
            coefficients = result.x
            report['RGB_refined'] = True
        report.update(optimizer_status=int(result.status), evaluations=result.nfev,
                      optimizer_converged=bool(result.success))
    return coefficients.reshape(405, 3), report


def quantize(coefficients):
    return native.encode(np.rint(coefficients).astype(int))
