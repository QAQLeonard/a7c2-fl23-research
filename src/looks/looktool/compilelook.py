"""DCP or explicit-input CUBE -> fitted four-stage .a7look, no USB."""
import argparse
import json
import os
from pathlib import Path
import shutil


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def cube_targets(source,path,input_space,bridge=None):
    import numpy as np
    from .references import Cube
    if not input_space or (input_space=='sony-st-srgb')==bool(bridge):
        raise ValueError('Specify Sony ST sRGB directly, or a named input space and an explicit bridge')
    source=np.asarray(source)
    entering=Cube(bridge).sample(source) if bridge else source
    value=Cube(path).sample(entering)
    return np.clip(value,0,1),dict(input_space=input_space,output_space='srgb',
        bridge_used=bool(bridge),clipped_output_components=int(((value<0)|(value>1)).sum()),
        Lightroom_reference_used=False,automatic_Adobe_profile_generated=False)


def dcp_targets(source,path,bridge=None):
    """Evaluate supported DCP look/tone stages locally against the ST bridge."""
    import numpy as np
    from .references import DcpLook
    from .calibration import inverse_st,validate
    from .rawprofiles import dcp_info
    root=Path(__file__).resolve().parents[3]
    bridge_path=Path(bridge) if bridge else root/'src/looks/assets/rendering-model-v1.json'
    mapping=validate(json.loads(bridge_path.read_text(encoding='utf-8')),True)
    info=dcp_info(path)
    if info['model']!='Sony ILCE-7CM2':raise ValueError('Select a Sony ILCE-7CM2 DCP; foreign sensor calibration is not copied')
    look=DcpLook(path)
    target=look.render(inverse_st(source,mapping),float(mapping.get('reference_exposure_stops',0)))
    report=look.inventory()
    report.update(renderer='builtin-DCP-look-tone',Lightroom_reference_used=False,
        bridge_evidence=mapping['evidence'],bridge_is_shared_approximation=bridge is None,
        calibration_scope='LookTable and ProfileToneCurve only; camera matrices and HueSat maps are not copied',
        camera_io=False)
    return np.clip(target,0,1),report,info


def split_colors(source, valid):
    import numpy as np
    bins=np.floor(np.clip(source,0,.9999)*4).astype(int)
    groups=bins[:,0]*16+bins[:,1]*4+bins[:,2]
    unique=np.unique(groups[valid]);np.random.default_rng(43917).shuffle(unique)
    a,b=round(.6*len(unique)),round(.8*len(unique))
    masks=[valid&np.isin(groups,part) for part in (unique[:a],unique[a:b],unique[b:])]
    if min(int(mask.sum()) for mask in masks)<25:raise ValueError('Insufficient separate virtual color groups')
    return masks


def fit(model, source, target, work, *, passes, evaluations):
    import numpy as np
    from . import nativefit, coupledfit, photomeasure
    coordinates=model.base.coordinates(source)
    valid=(source.min(1)>.015)&(source.max(1)<.985)&(coordinates.min(1)>-.05)&(coordinates.max(1)<1.05)
    train,validation,test=split_colors(source,valid)
    trials=[];best=None;rng=np.random.default_rng(15719)
    for index in range(passes):
        smooth=(1e-11,1e-10,1e-9)[index%3] if index<3 else best[0]['smooth']
        loss='soft_l1' if index>=3 and index%2 else 'linear'
        problem=nativefit.Problem(model,source[train],target[train],smooth)
        file=work/f'pass-{index+1:03}.npz';note=work/f'pass-{index+1:03}.json'
        if file.exists() and note.exists():
            vector=np.load(file,allow_pickle=False)['vector'];optimizer=json.loads(note.read_text(encoding='utf-8'))
        else:
            initialization=None
            if index<3:initial,initialization=nativefit.table_seed(problem,max_evaluations=evaluations,return_report=True)
            else:
                initial=best[1].copy()
                initial[1215:]=np.clip(initial[1215:]+rng.normal(0,.08,17),-.5,.5)
            vector,optimizer=nativefit.solve(problem,initial,max_evaluations=evaluations,loss=loss)
            if initialization is not None:optimizer['initialization']=initialization
            np.savez_compressed(file,vector=vector);save(note,optimizer)
        check=nativefit.Problem(model,source[validation],target[validation],smooth)
        metrics=coupledfit.metrics(check.prediction(vector),target[validation])
        trial=dict(pass_number=index+1,smooth=smooth,loss=loss,selection=metrics,optimizer=optimizer)
        trials.append(trial)
        if best is None or metrics['RGB_MAE_8bit']<best[0]['selection']['RGB_MAE_8bit']:
            best=(trial,vector.copy())
        save(work/'progress.json',dict(stage='fitting',completed_passes=index+1,
            best_selection=best[0],trials=trials,camera_io=False))
        print(f'Fit {index+1}/{passes}: validation MAE {metrics["RGB_MAE_8bit"]:.3f}; best {best[0]["selection"]["RGB_MAE_8bit"]:.3f}',flush=True)
    smooth=best[0]['smooth'];retained=train|validation
    def refit(mask,initial,label):
        problem=nativefit.Problem(model,source[mask],target[mask],smooth)
        file=work/(label+'.npz')
        if file.exists():vector=np.load(file,allow_pickle=False)['vector'];report=json.loads((work/(label+'.json')).read_text(encoding='utf-8'))
        else:
            vector,report=nativefit.solve(problem,initial,max_evaluations=evaluations,loss=best[0]['loss'])
            np.savez_compressed(file,vector=vector);save(work/(label+'.json'),report)
        return vector,report
    suffix='-pass'+str(best[0]['pass_number'])
    validation_vector,validation_optimizer=refit(retained,best[1],'validation-model'+suffix)
    check=nativefit.Problem(model,source[test],target[test],smooth)
    heldout=coupledfit.metrics(check.prediction(validation_vector),target[test])
    vector,optimizer=refit(valid,validation_vector,'final-model'+suffix)
    full=nativefit.Problem(model,source[valid],target[valid],smooth)
    predicted=full.prediction(vector)
    report=dict(camera_io=False,source='numerical target colors and measured camera response',
        virtual_color_groups=dict(train=int(train.sum()),selection=int(validation.sum()),test=int(test.sum())),
        budget=dict(passes=passes,max_evaluations_per_solve=evaluations),selected_trial=best[0],
        virtual_heldout_validation_replica=heldout,
        final_all_virtual_color_prediction=coupledfit.metrics(predicted,target[valid]),
        validation_optimizer=validation_optimizer,final_optimizer=optimizer,
        native_controls=photomeasure.quantized(vector[1215:]),native_bound=.5,
        actual_camera_error=None,physical_color_accuracy_verified=False,
        warning='Surrogate prediction only; response calibration error and unmeasured WB/gamut are not removed by more optimization')
    np.savez_compressed(work/'comparison.npz',source=source[valid],target=target[valid],prediction=predicted)
    return np.rint(vector[:1215]).reshape(405,3),report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--name',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--calibration',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--work',type=Path)
    parser.add_argument('--passes',type=int,default=3,help='Number of multi-start candidates; increase for more compute')
    parser.add_argument('--evaluations',type=int,default=100,help='Compute budget per fit; retain the best approximation when reached')
    parser.add_argument('--extra-colors',type=int,default=256)
    parser.add_argument('--dcp-bridge',type=Path,help='Optional measured ST-to-DCP working-space mapping JSON; default is the bundled approximation')
    parser.add_argument('--input-space',help='CUBE input: sony-st-srgb, or a named space with --bridge')
    parser.add_argument('--bridge',type=Path,help='CUBE mapping Sony ST sRGB into the input space')
    parser.add_argument('--raw-dcp',type=Path,help='Optional matching A7C II DCP for CUBE-source Lightroom imports')
    args=parser.parse_args(argv)
    cube_input=args.source.suffix.lower()=='.cube'
    if args.source.suffix.lower() not in ('.dcp','.cube') or not args.source.is_file():parser.error('Select an existing DCP or CUBE')
    if cube_input:
        if not args.input_space:parser.error('CUBE requires --input-space; a log/video LUT is not Sony ST sRGB')
        if (args.input_space=='sony-st-srgb')==bool(args.bridge):parser.error('Direct ST CUBE uses no bridge; other input spaces require --bridge')
    elif args.input_space or args.bridge or args.raw_dcp:parser.error('CUBE input-space/bridge/raw-dcp options do not apply to DCP')
    if args.output.exists():parser.error('Output already exists; choose a new .a7look filename')
    if args.output.suffix.lower()!='.a7look':parser.error('Output must use .a7look')
    if args.passes<1 or args.evaluations<1 or args.extra_colors<0:parser.error('Positive fitting budget required')
    root=Path(__file__).resolve().parents[3]
    config_path=args.config or root/'a7look-compiler.local.json'
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    calibration=args.calibration or Path(config.get('calibration',root/'calibration/a7c2-2.01.virtual.npz'))
    if not args.calibration and not calibration.is_absolute():calibration=config_path.parent/calibration
    if not calibration.is_file():parser.error('The measured A7C2 response snapshot is missing')
    if len(args.name.encode('utf-8'))>63 or not args.name or any(ord(c)<32 for c in args.name):parser.error('Name must use 1..63 UTF-8 bytes')
    os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('OMP_NUM_THREADS','2')
    import numpy as np
    from . import measuredmodel,lookfile,photobasis,photoformat,photomeasure,native,rawidentity
    model=measuredmodel.Response(calibration)
    profile={}
    work=args.work or args.output.with_suffix('.work');work.mkdir(parents=True,exist_ok=True)
    source_copy=work/('input.cube' if cube_input else 'input.dcp')
    if source_copy.exists() and source_copy.read_bytes()!=args.source.read_bytes():parser.error('Work directory belongs to a different source file')
    if not source_copy.exists():shutil.copyfile(args.source,source_copy)
    raw_profile=None
    if not cube_input:
        from .references import tiff_tags
        profile_order,profile=tiff_tags(source_copy.read_bytes())
        raw_profile=rawidentity.descriptor(source_copy,args.name)
        raw_profile['source_filename']=args.source.name
    elif args.raw_dcp:
        paired=work/'raw-source.dcp'
        if paired.exists() and paired.read_bytes()!=args.raw_dcp.read_bytes():parser.error('Work directory belongs to a different paired DCP')
        if not paired.exists():shutil.copyfile(args.raw_dcp,paired)
        raw_profile=rawidentity.descriptor(paired,args.name)
        raw_profile['source_filename']=args.raw_dcp.name
    settings={}
    gains=config.get('sensor_RGB_gains',model.metadata.get('sensor_RGB_gains',[1.,1.,1.]))
    identity=dict(name=args.name,extra_colors=args.extra_colors,evaluations=args.evaluations,
                  calibration=str(calibration.resolve()),reference_settings=settings,sensor_RGB_gains=gains)
    identity.update(source_type='cube' if cube_input else 'dcp',input_space=args.input_space,
                    renderer='explicit-CUBE-input' if cube_input else 'builtin-DCP-look-tone',
                    dcp_bridge=str(args.dcp_bridge.resolve()) if args.dcp_bridge else None,
                    bridge=str(args.bridge.resolve()) if args.bridge else None)
    manifest=work/'input.json'
    if manifest.exists():
        previous=json.loads(manifest.read_text(encoding='utf-8'))
        if not cube_input and 'source_type' not in previous:previous.update(source_type='dcp',input_space=None,bridge=None)
        if previous!=identity:parser.error('Use a new work directory after changing name/calibration/reference settings')
    if not manifest.exists():save(manifest,identity)
    raw,source=model.virtual_samples(args.extra_colors)
    source_reference=None
    if cube_input:
        import base64
        if args.bridge:
            bridge_copy=work/'bridge.cube'
            if bridge_copy.exists() and bridge_copy.read_bytes()!=args.bridge.read_bytes():parser.error('Work directory bridge changed')
            if not bridge_copy.exists():shutil.copyfile(args.bridge,bridge_copy)
        target,contract=cube_targets(source,source_copy,args.input_space,work/'bridge.cube' if args.bridge else None)
        source_reference=dict(schema='a7c2-source-cube/1',filename=args.source.name,input_space=args.input_space,
            cube_base64=base64.b64encode(source_copy.read_bytes()).decode('ascii'))
        if args.bridge:source_reference.update(bridge_base64=base64.b64encode((work/'bridge.cube').read_bytes()).decode('ascii'))
        actual_settings={};chart={'profile':None}
        print('Fitting CUBE against the measured camera response; Lightroom is not required.',flush=True)
    else:
        target,dcp_report,profile_info=dcp_targets(source,source_copy,args.dcp_bridge)
        chart={'profile':profile_info['profile']};actual_settings={}
        print('Evaluating DCP LookTable and tone curve locally; no Lightroom, plugins, network or USB.',flush=True)
        print('The bundled ST mapping is a shared approximation; sensor matrices and HueSat calibration are not copied.',flush=True)
    table,report=fit(model,source,target,work,passes=args.passes,evaluations=args.evaluations)
    bank=photoformat.PhotoBank.unpack(model.arrays['baseline_bank'].tobytes())
    _,delta=photobasis.pack(bank,**photomeasure.knobs(report['native_controls']))
    photobasis.compile_delta(bank,delta)
    copyright_text=profile.get(50942,(0,0,b''))[2].rstrip(b'\0').decode('utf-8','replace')
    report.update(profile=chart['profile'],source_DCP=None if cube_input else args.source.name,
        source_CUBE=args.source.name if cube_input else None,cube_contract=contract if cube_input else None,reference_settings=settings,
        actual_Adobe_reference_settings={},
        calibration_scope=model.metadata['physical_scope'],model_error_included_in_metrics=False,
        native_stages_present=True,table_bytes=1215,
        reference_pipeline='explicit-CUBE-input' if cube_input else 'builtin-DCP-look-tone-v1',
        DCP_reference=None if cube_input else dcp_report,
        Lightroom_reference_used=False,
        spatial_lens_correction_fitted=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    lookfile.write(args.output,args.name,native.encode(table),method='CUBE-measured-native-four-stage-v1' if cube_input else 'builtin-DCP-look-tone-measured-native-four-stage-v1',
        attribution=copyright_text or 'Owner-provided DCP; original rights apply',metrics=report,native_photo=delta,
        raw_profile=raw_profile,
        source_reference=source_reference)
    save(work/'result.json',report)
    print('Created '+str(args.output.resolve()),flush=True)
    if not report['final_optimizer']['optimizer_converged']:
        print('已生成近似结果；最终优化未完全收敛。验证色样平均预测误差 %.2f / 255，不能代表实机色彩准确度。' %
              report['virtual_heldout_validation_replica']['RGB_MAE_8bit'],flush=True)
    print('Offline candidate; no camera connection or write was performed.',flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
