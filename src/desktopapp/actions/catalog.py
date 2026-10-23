"""Shared desktop action categories; no host-specific feature variants."""
CAMERA_ACTIONS = {'connect', 'usb_prepare', 'driver_uninstall', 'fl23_prepare', 'fl23_install', 'fl23_verify',
                  'restore', 'restore_auto', 'restore_verify', 'look_prepare', 'look_install',
                  'look_verify', 'look_restore', 'vertical_enable', 'vertical_disable',
                  'vertical_status', 'vertical_remove', 'sound_on', 'sound_off',
                  'sound_audition', 'sound_install', 'sound_verify', 'sound_restore_sound'}

POWER_ACTIONS = {'restore', 'restore_auto', 'fl23_install', 'look_install', 'look_restore',
                 'vertical_enable', 'vertical_disable', 'vertical_remove',
                 'sound_on', 'sound_off', 'sound_audition', 'sound_install', 'sound_restore_sound'}
DIRECT_ACTIONS = {'direct_fl23_enable', 'direct_fl23_disable', 'direct_vertical_enable', 'direct_vertical_disable', 'direct_slot_default',
                  'direct_look_import', 'direct_looks_import', 'direct_resume_looks', 'direct_factory_reset', 'direct_resume_factory', 'direct_install_all'}
DIRECT_ACTIONS |= {'direct_sound_enable','direct_sound_disable','direct_sound_restore','direct_resume_settings'}
DIRECT_ACTIONS |= {'direct_preview_native', 'direct_preview_legacy'}
POWER_ACTIONS |= DIRECT_ACTIONS
CAMERA_ACTIONS |= DIRECT_ACTIONS | {'direct_verify'}
POWER_ACTIONS.add('setup_all')
CAMERA_ACTIONS.add('setup_all')
CAMERA_ACTIONS.add('review_failed_names')
CAMERA_ACTIONS.add('usb_stability')
