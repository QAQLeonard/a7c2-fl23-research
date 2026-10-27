"""Preview-guard upgrades preserve the current and earlier pending upload ABI."""
import pytest
from looktool import device_layout,photoio,uploadgate,uploadpending
import test_photoio as photo_fixture


@pytest.fixture(scope='module')
def source():
    photo_fixture.PhotoIOTests.setUpClass()
    value=bytearray(photo_fixture.PhotoIOTests.source)
    for _,at,before,_ in uploadpending.WINDOWS:
        raw=bytes.fromhex(before);value[at:at+len(raw)]=raw
    for at,text in uploadpending.GUARDS:
        raw=bytes.fromhex(text);value[at:at+len(raw)]=raw
    value[uploadgate.OFFSET:uploadgate.OFFSET+4]=uploadgate.NATIVE
    at=uploadgate.OFFSET+4;value[at:at+len(uploadgate._FOLLOWING)]=uploadgate._FOLLOWING
    for row in device_layout.runtime()['superseded_windows']:
        raw=bytes.fromhex(row['after']);value[row['offset']:row['offset']+len(raw)]=raw
    return bytes(value)


def pending(source,legacy):
    if not legacy:return uploadpending.install(source)
    result=bytearray(source)
    for _,at,_,after in uploadpending.TRIAL2_WINDOWS:
        raw=bytes.fromhex(after);result[at:at+len(raw)]=raw
    return bytes(result)


@pytest.mark.parametrize('legacy',[False,True])
def test_helper_migration_preserves_every_pending_instruction(source,legacy):
    before=pending(source,legacy)
    after=photoio.preview_helper(before)
    assert after!=before and uploadpending.active(after)
    expected=photoio.preview_helper(source)
    assert uploadpending.normalize(after)==expected
    for _,at,_,raw in uploadpending.TRIAL2_WINDOWS if legacy else uploadpending.WINDOWS:
        assert after[at:at+len(bytes.fromhex(raw))]==before[at:at+len(bytes.fromhex(raw))]
    assert photoio.preview_helper(after)==after
    changed={i for i,(old,new) in enumerate(zip(before,after)) if old!=new}
    assert changed and all(0xb274f4<=i<0xb274f8 or 0xb27520<=i<0xb27558 for i in changed)


@pytest.mark.parametrize('legacy',[False,True])
def test_native_stage_upgrade_admits_the_previous_helper_with_pending(source,legacy):
    previous=pending(source,legacy)
    after=photoio.update(previous,{1:photo_fixture.PhotoIOTests.delta},photo_fixture.PhotoIOTests.bank,allocation_proved=True)
    assert photoio.inspect(after)['mask']==1
    assert uploadpending.active(after)
    normalized=uploadpending.normalize(photoio.underlay(after))
    assert normalized[0xb27520:0xb27558]==photoio.preview_helper(source)[0xb27520:0xb27558]


def test_unknown_guard_is_not_silently_replaced(source):
    previous=bytearray(pending(source,False));previous[0xb27528]^=1
    assert photoio.preview_helper(bytes(previous))==bytes(previous)
    with pytest.raises(ValueError,match='allocation conflicts'):
        photoio.allocation(bytes(previous))
