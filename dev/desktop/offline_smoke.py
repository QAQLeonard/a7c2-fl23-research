"""Exercise packaged imports, assets and an actual native compile, without USB."""
import importlib
from pathlib import Path
import tempfile


def check_dcp_conversion(selected):
    """Exercise shipped profiles and the real fitting pipeline in the package."""
    import numpy as np
    from looktool import compilelook, lookfile, rawidentity
    names=[]
    with tempfile.TemporaryDirectory(prefix='a7c2-dcp-smoke-') as temporary:
        folder=Path(temporary)
        for row in selected:
            source=folder/('slot%d.dcp'%row['slot'])
            source.write_bytes(rawidentity.source_bytes(row['document']['raw_profile']))
            target,report,info=compilelook.dcp_targets(np.array([[.1,.2,.3],[.8,.6,.4],[.3,.3,.3]]),source)
            assert target.shape==(3,3) and np.isfinite(target).all()
            assert not report['Lightroom_reference_used'] and not report['full_adobe_renderer']
            names.append(info['profile'])
        output=folder/'Astia.a7look'
        assert compilelook.main([str(folder/'slot4.dcp'),'--name','Offline package check',
            '--output',str(output),'--passes','1','--evaluations','20','--extra-colors','32'])==0
        document=lookfile.read(output)
        assert len(lookfile.writer_document(document))==1215
        assert document['native_photo']['runtime_basis']
        assert document['validation']['metrics']['Lightroom_reference_used'] is False
    return dict(profiles_evaluated=names,real_fit='passed',Lightroom_used=False,
                reduced_budget=True,physical_color_validated=False,camera_io=False)


def check_audio_conversion():
    """Convert generated mono/stereo/compressed audio using shipped dependencies.

    Importing sound_cli alone does not exercise its lazy media/codec imports.
    Keep this in the frozen self-test so omitted stdlib modules (such as wave)
    and a missing ffmpeg executable fail before a desktop build is distributed.
    """
    import math
    import struct
    import subprocess
    import wave
    import imageio_ffmpeg
    import media
    import native_codec
    import sound_cli
    import json

    executable = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve(strict=True)
    assert executable.is_file()
    results = {}
    with tempfile.TemporaryDirectory(prefix='a7c2-audio-smoke-') as temporary:
        root = Path(temporary)
        rate = 44100
        samples = [round(8000 * math.sin(2 * math.pi * 660 * i / rate))
                   for i in range(round(rate * .12))]
        mono = root / 'generated mono.wav'
        native_codec.write_wav(mono, samples, rate)
        stereo = root / 'generated stereo.wav'
        with wave.open(str(stereo), 'wb') as output:
            output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
            output.writeframes(b''.join(struct.pack('<hh', x, round(x / 2)) for x in samples))
        compressed = root / 'generated stereo.mp3'
        encoded = subprocess.run([str(executable), '-nostdin', '-v', 'error', '-n',
            '-i', str(stereo), '-c:a', 'libmp3lame', str(compressed)],
            capture_output=True, timeout=60)
        assert encoded.returncode == 0, encoded.stderr.decode('utf-8', errors='replace')
        for label, source in (('mono_wav', mono), ('stereo_wav', stereo), ('stereo_mp3', compressed)):
            original = source.read_bytes()
            output = root / label
            report = media.convert(source, output, duration=.08, peak=.4,
                                   ffmpeg=str(executable))
            payload = (output / 'custom-native.private.bin').read_bytes()
            preview, preview_rate = native_codec.read_wav(output / 'preview.private.wav')
            assert 0 < len(payload) <= 51200 and len(payload) % 64 == 0
            assert len(payload) == report['encoded_bytes']
            assert preview_rate == 24000 and len(preview) == 1920 and any(preview)
            assert preview == native_codec.decode(payload)[:len(preview)]
            assert source.read_bytes() == original and report['camera_io'] is False
            results[label] = 'passed'
        workspace=root/'pending-camera-task';workspace.mkdir()
        state=dict(schema=sound_cli.SCHEMA,pending=dict(command='on',outcome='needs_review',job='synthetic-native-job'))
        sound_cli.save(workspace,state)
        original_state=(workspace/'sound.private.json').read_bytes()
        converted=sound_cli.import_audio(workspace,state,mono,duration=.08,peak=.4)
        assert converted['camera_io'] is False and converted['phase']=='converted_offline'
        assert (workspace/'sound.private.json').read_bytes()==original_state
        assert (workspace/'conversion.private.json').is_file()
        results['unresolved_camera_task_does_not_block_conversion']='passed'
        initial=Path(sound_cli.selected_conversion(workspace,None))
        original_payload=(initial/'custom-native.private.bin').read_bytes()
        louder=sound_cli.volume_audio(workspace,decibels=3)
        assert louder['volume_gain_db']==3 and louder['camera_io'] is False
        adjusted=Path(sound_cli.selected_conversion(workspace,None))
        adjusted_preview,_=native_codec.read_wav(adjusted/'preview.private.wav')
        assert adjusted_preview==native_codec.decode((adjusted/'custom-native.private.bin').read_bytes())[:len(adjusted_preview)]
        sound_cli.volume_audio(workspace,reset=True)
        assert (Path(sound_cli.selected_conversion(workspace,None))/'custom-native.private.bin').read_bytes()==original_payload
        assert (workspace/'sound.private.json').read_bytes()==original_state
        results['offline_volume_and_exact_reset']='passed'
        import trial
        failed=workspace/'failed-enable';failed.mkdir()
        events=[dict(event=event,stage='shutter.staged.so',mode=0) for event in (
            'native_stage_intent','native_intent','native_result_verified','native_cleanup_verified')]
        evidence=dict(schema='a7c2-shutter-job/1',phase='needs_review',
            camera_firmware_written=False,journal=events)
        trial.save(failed,evidence)
        before=(failed/'job.private.json').read_bytes()
        state.update(history=[],native_job=str(failed),pending=dict(command='on',job=str(failed)))
        assert sound_cli.retire_readonly_failure(workspace,state)
        assert state['pending'] is None and state['native_job'] is None
        assert (failed/'job.private.json').read_bytes()==before
        evidence['journal']=[dict(e,mode=1) for e in events]
        assert not trial.completed_readonly_failure(evidence)
        results['completed_readonly_failure_released_unknown_write_still_blocked']='passed'
        import buffer_trial
        old=root/'completed-audio';old.mkdir()
        raw=bytearray(208)
        struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,10,0)
        struct.pack_into('<6I',raw,88,0,0xffffffff,1,1,1,0)
        struct.pack_into('<8I',raw,112,0,0,0,0,1,3776,1,0)
        struct.pack_into('<4I',raw,192,0,0,0xffffffff,1)
        prior=dict(identity={'model':'ILCE-7CM2','serial_sha256':'offline-only'},
                   result=buffer_trial.parse(raw),lease_token_hex=bytes(range(16)).hex())
        trial.save(old,prior);(old/'report.private.bin').write_bytes(raw)
        class MarkerCamera:
            identity=prior['identity']
            marker=buffer_trial.initial_marker(prior)
            def read(self,*args):return self.marker
            def temp_read(self,*args):return None
            def temp_remove(self,name):
                assert name=='shutter.custom.lease'
                self.marker=None
        marker_camera=MarkerCamera()
        replacement=buffer_trial.replace_completed_marker(marker_camera,root,[old])
        assert replacement['completed_prior_marker_replaced'] and marker_camera.marker is None
        assert replacement['previous_cp_handle_released'] is False
        results['completed_sound_marker_replaced_before_next_registration']='passed'
    return dict(results, preview_rate_hz=24000, camera_io=False,
                bundled_ffmpeg='passed')


def run():
    import usb.core
    def no_device(*args,**kwargs):
        raise AssertionError('Packaged offline self-test must never enumerate physical USB')
    usb.core.find=no_device
    from desktopapp.worker import setup_runtime
    from desktopapp.paths import ROOT
    setup_runtime()
    from desktopapp import reloadguide
    from desktopapp import connectionguide
    from desktopapp.exiftool import ensure
    import subprocess
    exiftool=ensure()
    exif_result=subprocess.run([exiftool,'-ver'],capture_output=True,text=True,timeout=30)
    assert exif_result.returncode==0, exif_result.stderr
    assert '请检查所连接的设备' in connectionguide.TEXT and '正常现象' in connectionguide.TEXT
    audition=dict(phase='temporary_pcm_registered_cold_reload_required_after_test')
    assert not reloadguide.required('sound_audition',audition)
    assert '保持相机开机' in reloadguide.sound_notice('sound_audition',audition)['text']
    assert '试听是可选步骤' in reloadguide.sound_notice('sound_install',dict(phase='sound_conversion_required'))['text']
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    instruction=bytes(Ks(KS_ARCH_ARM,KS_MODE_THUMB).asm('bx lr')[0])
    assert next(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(instruction,0)).mnemonic=='bx'
    # Emulator execution belongs in developer tests. A frozen macOS worker
    # must not require writable/executable JIT memory merely to save a sound.
    import sys
    if str(ROOT / 'src/shutter_sound') not in sys.path:sys.path.insert(0,str(ROOT / 'src/shutter_sound'))
    import boot_sound
    assert boot_sound.expected_windows()[-1][0]==boot_sound.BOOT
    importlib.import_module('desktopapp.allinone')
    from desktopapp import allinone, presets, lookbatch, reviewnames, completion
    from looktool import bundle
    from looktool import device_layout
    assert bytes.fromhex('002c04d1132802d3142898bf002049f6f811c0f22011704700bf') in device_layout.fl23_previous_values(0x138832)
    assert len(device_layout.fl23_previous_values(0x1100b80))>=2
    packed, selected = bundle.documents(presets.resolve(dict(preset_pack=presets.PACK)))
    assert [row['name'] for row in selected] == list(presets.NAMES)
    defaults=lookbatch.options(presets.catalog())
    assert len(defaults['looks'])==6 and defaults['fl23'] is False and defaults['sound'] is False
    mixed=lookbatch.options([dict(slot=4,action='restore'),dict(presets.catalog()[1],action='write')])
    assert mixed['reset_slots']==[4] and [r['slot'] for r in mixed['looks']]==[2]
    assert not mixed['fl23'] and not mixed['sound'] and not mixed['vertical_persistent']
    importlib.import_module('desktopapp.lookeditor')
    with tempfile.TemporaryDirectory() as temporary:
        calls=[]
        def simulated(action,args,folder):
            calls.append(action)
            if action=='voice_cleanup':return dict(voice_audio_removed=True,voice_setting_locked_off=True,voice_menu_flags_verified=True)
            if action == 'direct_install_all':
                assert args['options']['vertical_persistent'] is True
                _, rows = bundle.documents(args['options'])
                assert [r['name'] for r in rows] == list(presets.NAMES)
                assert all(Path(r['path']).parent.resolve() == (Path(temporary) / 'inputs').resolve() for r in rows)
            return {'phase':'LOADED','mode':'install_all','workspace':args.get('workspace',''),
                'vertical_result':dict(persistent=True,loaded_verified=True,saved='ON',running='ON',alias_count=3)}
        result=allinone.run(dict(workspace=temporary,firmware='2.01',power_confirmed=True,
            options=dict(fl23=False,sound=False,vertical=True,plugin=False,preset_pack=presets.PACK)),dispatch=simulated)
        assert result['phase']=='COMPLETE' and not result['physical_checks_accepted']
        assert calls==['usb_prepare','voice_cleanup','vertical_enable','direct_install_all']
        assert '电子快门声：本次未选择' in completion.text(result)
        assert completion.console_summary(result)['phase']=='COMPLETE'
        assert '无需每次连接电脑' in completion.text(result)
    from looktool import nativebuild, checkpointworker, device_layout, resources, nameworker
    from looktool.devicesession import modules
    transport, core = modules()
    assert nativebuild.ROOT == ROOT
    assert Path(core.__file__).resolve() == ROOT / 'src/camera_runtime/core.py'
    assert core.assets()
    core.merge_colors(bytes(8192), bytes(28672))
    assert device_layout.runtime()['schema'] == 'a7c2-lut-runtime/1'
    native_windows=device_layout.fl23_native_windows()
    gamma=next(new for at,old,new,legacy in native_windows if at==0x1100b80)
    import struct
    assert struct.unpack_from('<II',gamma,0xe78+19*8)==(48,46)
    assert struct.unpack_from('<II',gamma,0xe78+20*8)==(49,47)
    assert device_layout.fl23_previous_values(0x1100b80)
    assert (ROOT / 'src/looks/assets/native-photo-v2.json').is_file()
    for name in ('compilelook', 'lookfile', 'rawauto', 'rawprofiles', 'checkpointjob', 'devicejob', 'direct', 'requestcleanup', 'bundle','namespause','verticalpersist'):
        importlib.import_module('looktool.' + name)
    import sys
    sys.path.insert(0, str(ROOT / 'src/desktopapp/vendor'))
    from fwtool.sony import dat, fdat
    from fwtool.archive import ext2, fat
    from desktopapp.official import layout
    assert layout()['version'] == '2.01'
    sys.path[:0] = [str(ROOT / 'src/vertical'), str(ROOT / 'src/shutter_sound')]
    importlib.import_module('verticaltool.device')
    importlib.import_module('looktool.portraitjob')
    importlib.import_module('verticaltool.nativeportrait')
    importlib.import_module('desktopapp.vertical_native')
    from desktopapp.disclaimer import terms_text
    assert 'DMCA' in terms_text() and 'LICENSE' in terms_text()
    assert '不撤回' not in terms_text() and '从未授权任何人' in terms_text()
    from verticaltool import imagebank, portraitbank, portraitworker
    import struct
    with tempfile.TemporaryDirectory(prefix='a7c2-portrait-smoke-') as temporary:
        plans=[]
        for group in (0,1):
            count=7844 if group==0 else 7880
            slots=(count+1)&~1
            raw=bytearray(struct.pack('<8sHHI',imagebank.MAGIC,8,group,count|(slots<<12)))
            raw.extend(b'\xff\xff'*slots);base=len(raw)
            if group==1:
                # Sony's original Creative Look panel (0x291) with its 20-byte slice options.
                struct.pack_into('<H',raw,16+2*0x291,(len(raw)-base)//4)
                raw.extend(struct.pack('<IIHH',0x1a000000+8192+0x291,0x48000000,8,8))
                raw.extend(bytes.fromhex('020001000000000000007e0000007e0000000000'))
                raw.extend(struct.pack('<II',16,36)+bytes(16))
            # One existing payload, after all metadata, large enough to relocate for the new records.
            struct.pack_into('<H',raw,16,(len(raw)-base)//4)
            raw.extend(struct.pack('<IIHHII',0x1a000000+group*8192,0x40000000,8,8,2048,16))
            raw.extend(bytes(range(256))*8)
            original,target,plan=portraitbank.prepare(bytes(raw),group)
            assert portraitbank.prepare(target,group)==(original,target,plan)
            assert imagebank.apply(target,plan,reverse=True)==original
            plans.append(plan)
        frames=portraitworker.build(plans,bytes(128),temporary,
            ap_windows=[dict(offset=32,before_hex=bytes(4).hex(),after_hex=b'NEW!'.hex())])
        assert Path(frames['path']).read_bytes()[:4]==b'\x7fELF'
        assert Path(frames['path']).stat().st_size<=65536
    assert (ROOT / 'src/vertical/assets/aliases_recovery.so').read_bytes()[:4] == b'\x7fELF'
    importlib.import_module('sound_cli')
    audio_conversion = check_audio_conversion()
    dcp_conversion = check_dcp_conversion(selected)
    import numpy as np
    import scipy.optimize
    from looktool.measuredmodel import Response
    model = Response(ROOT / 'calibration/a7c2-2.01.virtual.npz')
    with tempfile.TemporaryDirectory() as folder:
        before = {'appFw.so': bytes(40000), 'cpapp-b.bin': bytes(40000)}
        after = dict(before, **{'appFw.so': b'\x01' + bytes(39999)})
        builds = checkpointworker.build_programs(before, after, Path(folder))
        assert builds and Path(builds[0]['path']).read_bytes()[:4] == b'\x7fELF'
        import struct
        count = 2860
        raw = bytearray(b'uxc\x07\0\0\0\0' + struct.pack('<HHI', 8, 5, count | (count << 12)) + b'\xff\xff' * count)
        struct.pack_into('<H', raw, 16, 0)
        raw.extend(struct.pack('<I', 0x1e00a000) + b'Native\0\0')
        original = bytes(raw)
        renamed = resources.rename(original, {1: 'Smoke'})[0]
        current = {'resources/' + name: renamed for name in nameworker.filenames()}
        target = {'resources/' + name: original for name in nameworker.filenames()}
        names = checkpointworker.build_names(current, target, Path(folder), 'smoke')
        assert Path(names['path']).read_bytes()[:4] == b'\x7fELF'
        assert '#define CHECKPOINT_STREAM_RESTORE 1' in (Path(folder) / 'names.private.h').read_text()
        _,forward=nameworker.prepare({n:original for n in nameworker.filenames()},{1:'Smoke'},bytes(16),
            '0123456789abcdef',Path(folder)/'forward',byte_only=True)
        assert forward['stream_install'] and Path(forward['path']).read_bytes()[:4]==b'\x7fELF'
    return {'camera_io': False, 'project_imports': 'passed', 'bundled_exiftool':exif_result.stdout.strip(), 'assets': 'passed', 'builtin_factory_reference': 'passed',
            'native_cross_compile': 'passed', 'native_assembler_disassembler':'passed',
            'one_click_offline_sequence':'passed','look_batch_defaults':'passed','streaming_names_compile':'passed',
            'bundled_six_looks':list(presets.NAMES),'fl23_pr6_movie_routes':'passed',
            'completion_summary':'passed','persistent_vertical_plan':'passed','portrait_frames_compile_and_inverse':'passed',
            'audio_conversion':audio_conversion,'standalone_dcp_conversion':dcp_conversion,
            'sound_install_byte_planner':'passed','numpy': np.__version__}
