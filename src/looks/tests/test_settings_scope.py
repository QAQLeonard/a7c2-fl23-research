"""Live telemetry must not block imports; writable settings stay protected."""
import copy,unittest
from looktool import devicesettings
from test_device_job import Prop,core

class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.before=[{0x02cf0001:Prop(b'\0',0),0x02cf0002:Prop(b'\1',0),
            0x02770015:Prop((100).to_bytes(4,'little'),2),
            devicesettings.SAVED_TELEMETRY:Prop(bytes(4),64)},
            {k:Prop(b'original-calibration',0) for k in devicesettings.PROTECTED}]
        self.after=copy.deepcopy(self.before)
    def compare(self,expected=None):return devicesettings.compare(self.before,self.after,expected or {},core)
    def test_runtime_and_diagnostic_values_do_not_block_and_are_not_written(self):
        self.after[0][0x02770015]=Prop((999999).to_bytes(4,'little'),2)
        self.after[0][devicesettings.SAVED_TELEMETRY]=Prop(b'xxxx',64)
        self.after[0][0x02780000]=Prop(b'unrelated-live-state',0)
        self.assertEqual(self.compare()['preserved_properties'],6)
    def test_selected_exact_readback_and_all_unselected_ap_settings_required(self):
        self.after[0][0x02cf0001]=Prop(b'\3',0)
        self.compare({0x02cf0001:'03'})
        for expected in [{},{0x02cf0001:'04'}]:
            with self.assertRaises(ValueError):self.compare(expected)
        self.after[0][0x02cf0002]=Prop(b'\2',0)
        with self.assertRaises(ValueError):self.compare({0x02cf0001:'03'})
    def test_missing_changed_attributes_and_added_ap_setting_stop(self):
        for action in ['missing','attribute','added','diagnostic-layout']:
            self.after=copy.deepcopy(self.before)
            if action=='missing':del self.after[0][0x02cf0002]
            elif action=='attribute':self.after[0][0x02cf0002]=Prop(b'\1',1)
            elif action=='added':self.after[0][0x02cf0003]=Prop(b'\0',0)
            else:self.after[0][devicesettings.SAVED_TELEMETRY]=Prop(b'xxxx',0)
            with self.assertRaises(ValueError):self.compare()
    def test_each_protected_cp_unit_and_write_scope_remain_required(self):
        for key in devicesettings.PROTECTED:
            self.after=copy.deepcopy(self.before);self.after[1][key]=Prop(b'changed',0)
            with self.assertRaises(ValueError):self.compare()
            del self.after[1][key]
            with self.assertRaises(ValueError):self.compare()
        self.after=copy.deepcopy(self.before)
        for key in [0x02770015,devicesettings.SAVED_TELEMETRY,devicesettings.PROTECTED[0],0x02cf9999]:
            with self.assertRaises(ValueError):self.compare({key:'00'})

    def test_fl23_allows_exact_color_targets_but_keeps_other_calibration_protected(self):
        target=b'new-color-unit'
        self.after[1][0x02a40001]=Prop(target,0)
        self.after[0][0x02770015]=Prop((160).to_bytes(4,'little'),2)
        devicesettings.compare(self.before,self.after,{},core,expected_cp={0x02a40001:target.hex()})
        with self.assertRaises(ValueError):self.compare()
        self.after[1][0x02a40002]=Prop(b'changed-calibration',0)
        with self.assertRaises(ValueError):
            devicesettings.compare(self.before,self.after,{},core,expected_cp={0x02a40001:target.hex()})
        with self.assertRaises(ValueError):
            devicesettings.compare(self.before,self.after,{},core,expected_cp={0x02a40002:'00'})

if __name__=='__main__':unittest.main()
