"""Compilation resumes only while the numerical inputs remain unchanged."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from looktool import compilelook, measuredmodel
from test_compile_dcp_offline import dcp


@pytest.mark.parametrize('source_type,changed',[
    ('dcp','calibration'),('cube','calibration'),
    ('dcp','custom_bridge'),('dcp','bundled_bridge'),
    ('dcp','legacy_manifest'),('cube','legacy_manifest'),
])
def test_resume_rejects_changed_input_contents(tmp_path,monkeypatch,capsys,source_type,changed):
    bundled=Path(compilelook.__file__).resolve().parents[3]/'src/looks/assets/rendering-model-v1.json'
    bridge=tmp_path/'src/looks/assets/rendering-model-v1.json'
    bridge.parent.mkdir(parents=True)
    bridge.write_bytes(bundled.read_bytes())
    monkeypatch.setattr(compilelook,'__file__',str(tmp_path/'src/looks/looktool/compilelook.py'))
    calibration=tmp_path/'response.npz'
    np.savez(calibration,response=np.array([1.]))
    source=tmp_path/('source.'+source_type)
    work=tmp_path/'work';output=tmp_path/'result.a7look'
    argv=[str(source),'--name','Resume fixture','--output',str(output),
          '--calibration',str(calibration),'--work',str(work)]
    if source_type=='cube':
        source.write_text('LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n')
        argv.extend(['--input-space','sony-st-srgb'])
    else:
        dcp(source)
        if changed=='custom_bridge':
            custom=tmp_path/'custom.json';custom.write_bytes(bridge.read_bytes());bridge=custom
            argv.extend(['--dcp-bridge',str(bridge)])
    colors=np.array([[.2,.3,.4],[.5,.6,.7]])
    model=SimpleNamespace(metadata={},virtual_samples=lambda count:(colors,colors))
    with patch.object(measuredmodel,'Response',return_value=model), \
         patch.object(compilelook,'fit',side_effect=RuntimeError('interrupted fit')) as fit:
        with pytest.raises(RuntimeError,match='interrupted fit'):
            compilelook.main(argv)
        # Keep a completed pass from the interrupted job, as the real fitter does.
        cache=work/'pass-001.npz';np.savez(cache,vector=np.zeros(1232))
        (work/'pass-001.json').write_text(json.dumps(dict(optimizer_converged=True)))
        cache_bytes=cache.read_bytes()
        with pytest.raises(RuntimeError,match='interrupted fit'):
            compilelook.main(argv)
        assert fit.call_count==2
        if changed=='calibration':
            np.savez(calibration,response=np.array([2.]))
        elif changed.endswith('bridge'):
            mapping=json.loads(bridge.read_text())
            mapping['reference_exposure_stops']+=1
            bridge.write_text(json.dumps(mapping))
        else:
            manifest=work/'input.json';identity=json.loads(manifest.read_text())
            identity={key:value for key,value in identity.items() if not key.endswith('_sha256')}
            manifest.write_text(json.dumps(identity))
        with pytest.raises(SystemExit) as error:
            compilelook.main(argv)
        assert error.value.code==2
        assert 'new work directory' in capsys.readouterr().err
        assert fit.call_count==2
        assert cache.read_bytes()==cache_bytes
        assert not output.exists()
