"""User-visible cold reload steps, shared by the log and completion dialog."""

STEPS = (
    '仅在软件明确显示“读写已结束”后操作。\n\n'
    '1. 拔掉相机 USB 数据线，并断开其他外部供电。\n'
    '2. 等待相机存取灯停止闪烁，不要在灯闪烁时取电池。\n'
    '3. 将相机电源拨到 OFF，等屏幕和存取灯完全熄灭。\n'
    '4. 取下电池，让相机同时没有电池、USB 和其他供电，至少等待 1 分钟。\n'
    '5. 装回电池并开机。'
)

WAITING_PHASES = {'WAIT_RELOAD', 'AWAITING_RELOAD', 'RESTORED_AWAITING_RELOAD',
                  'installed_pending_cold_start','WAIT_RESOURCE_RELOAD','AWAITING_RESOURCE_RELOAD','WAIT_VOICE_RELOAD'}
SOUND_PHASES = {
    'sound_on': {'written'}, 'sound_off': {'restored'},
    'sound_install': {'installed_cold_test_pending'},
    'sound_restore_sound': {'restored_cold_test_pending'},
    'sound_confirm': set(),
}


def required(action, result):
    """Use completed backend outcomes, never guess from a write button name."""
    phase = result.get('phase')
    if result.get('reload_required') is True:
        return True
    if phase in WAITING_PHASES:
        return True
    return (phase in SOUND_PHASES.get(action, set())
            and not result.get('adopted_existing_enabled'))


def sound_notice(action,result):
    """Temporary audition needs guidance while the current power stays on."""
    phase=result.get('phase')
    if action=='sound_audition' and phase=='temporary_pcm_registered_cold_reload_required_after_test':
        return dict(title='试听已准备好，请保持相机开机',
            status='试听已准备好。拔 USB 并保持开机，试拍后接回即可直接保存。',
            text='相机读写已结束。当前声音只供临时试听，尚未永久保存。\n\n'
                 '1. 拔掉 USB，保持相机开机；不要关机、取下电池或更改音频信号设置。\n'
                 '2. 使用电子快门拍一张，检查声音内容、音量、音调／速度，以及拍摄和回放是否正常。\n'
                 '3. 接回 USB 海量存储，点击“保存为电子快门专属音效”。可以直接保存，无需先恢复原声。\n'
                 '4. 保存写入完成后，再按弹窗完整断电重开，检查是否永久生效。\n\n'
                 '“确认试听正确”只记录试听结果，是可选步骤。\n'
                 '本弹窗的“确定”只关闭说明，不代表已确认试听正确。')
    if action=='sound_confirm' and phase in ('owner_confirmed_audio_cold_reload_required',
            'owner_audio_failed_cold_reload_required','owner_requested_gain_adjustment_cold_reload_required'):
        return dict(title='试听结果已记录',status='试听记录已保存；可直接保存为电子快门专属音效，无需先断电恢复。',
                    text='这一步只记录试听结果。\n\n可直接点击“保存为电子快门专属音效”，无需先断电或记录恢复。'
                    '若不满意，调整片段后重新转换；需要清除临时试听时，再按断电步骤恢复原声。')
    if action!='sound_install':return None
    if phase=='sound_conversion_required':
        return dict(title='保存尚未开始，请先转换片段',status='等待操作：选择声音文件，转换后即可直接保存。',
                    text='尚无可保存的转换片段，本次没有相机写入。\n\n选择音频或视频，设置起点和长度，'
                    '点击“转换所选片段”；转换成功后直接点击“保存为电子快门专属音效”。试听是可选步骤。')
    return None


def text(*, setup=False, mode=None):
    if mode=='vertical_native_prepare':
        return ('旧竖屏引用和刻度补偿已撤回，尚未复制独立竖屏资源。请先让相机加载原生绘制路径。\n\n'+STEPS+
            '\n\n重开后接回 USB 海量存储，再点击“开启竖屏显示”；一键安装则点击“继续安装”。'
            '程序会核对已加载的原生路径，完整复制并读回三份竖屏资源后才保存开启。')
    if mode=='voice_disable':
        return ('语音指南关闭限制及菜单置灰已写入，尚未删除音频。必须先让相机加载关闭限制与菜单禁用状态。\n\n'+STEPS+
            '\n\n重开后接回 USB 海量存储，再点击首页“继续安装”。'
            '程序会核对实际加载的关闭限制；核对不符时不删除或写回语音文件。')
    if mode=='voice_unlock':
        return ('语音文件已完整写回并读回，关闭限制已解除。\n\n'+STEPS+
            '\n\n重开后语音指南保持关闭，可以在机内按需要开启。请检查菜单、取景和拍摄。')
    if mode in ('preview_native', 'preview_legacy', 'preview_pending'):
        return ('本轮 LUT 刷新候选的写入和完整读回已结束，尚未证明横线与实时预览问题已修复。\n\n'+STEPS+
                '\n\n下一步：保持原先能复现横线的帧率和拍摄模式，检查高刷新率取景器、背屏及录像；'
                '在 ST 与六个自定义槽之间反复切换，确认预览及时变化，再拍照并回放。\n\n'
                '接回 USB 后，在本测试区域点击“断电重开后只读核对本轮测试”。'
                '只在完成机身检查后勾选验收；磁盘读回和 AP 加载核对不等于 CP RAM 或屏幕时序验证。'
                '\n\n若切换后色彩不更新或出现新异常，保留日志，可用本测试区域的“撤回测试：恢复旧版刷新方式”撤回本轮候选。')
    if mode=='factory_reset':
        return ('恢复尚未完成：本次写入和完整读回已结束，还必须重启后核对相机实际加载状态。\n\n'+STEPS+
                '\n\n下一步：确认相机能正常取景，接回 USB 海量存储，点击恢复页'
                '“继续完成一键恢复”。\n\n'
                '只有核对通过才显示恢复完成。核对失败时保留日志，不要把写入结束当成恢复完成。'
                '弹窗“确定”只关闭说明，不会自动完成核对。')
    if mode=='resource_reload':
        return ('名称阶段已完成，程序尚未写入。旧资源仍被相机占用，只读挂载尚未恢复；需要先释放旧资源，再继续剩余安装。\n\n'+STEPS+
            '\n\n开机后先不用拍照。接回 USB 海量存储，再点'+('首页“继续安装”' if setup else '自定义外观页“继续槽位更改”')+
            '。工具会核对新的冷启动和只读挂载，然后继续剩余程序，不重复写名称、不重装驱动。\n\n程序写完后还会提示最终重开，让新功能生效。点确定只关闭说明。')
    reason = ('\n\n这次“启用 FL2／FL3”已写入程序文件。此前恢复原厂后的重开只加载了原厂状态；本次新的修改需要再次重开才能生效。'
              if mode == 'fl23_enable' else '')
    follow = ('接回 USB，选择海量存储，再点首页“继续安装”。工具先核对加载，不重复刷写。'
              if setup else '在相机中确认 FL2／FL3 能选择、拍摄及回放，即可使用。不必再接电脑点击核对；如需排查，可使用 FL23 页的可选诊断。'
              if mode in ('fl23_enable', 'fl23_disable') else
              '此次断电仅用于清除临时试听、恢复原声，不是保存声音的前置条件。开机确认原声、拍摄及回放正常，可点声音页“已断电恢复原声，记录恢复完成”。保存当前转换片段不需要先执行这一步。'
              if mode == 'sound_confirm' else
              '开机后分别用机械快门和电子快门拍摄，检查扬声器音效按各自开关播放，并确认对焦提示音、拍摄和回放。机械结构本身的咔嗒声仍然存在。保存自定义声音后，可在声音页核对加载状态。'
              if mode and mode.startswith('sound_') else
              '独立竖屏资源与原生开关已准备。重开后先横握检查 Fn 网格和右移选择，再分别左右竖握检查 Fn、创意外观外框、橙色指针和触摸／按键方向，最后检查拍摄和回放。此候选尚未真机验收，不把文件读回当成显示正常。'
              if mode == 'vertical_enable' else
              '竖屏已先关闭，原线框引用与资源索引已恢复，辅助别名已移除。如果当前运行仍引用追加图片，会暂时保留少量图片尾部数据，避免破坏当前显示；这不影响关闭效果，也不需要再点按钮。重开后确认横握／竖握显示及拍摄正常。'
              if mode == 'vertical_disable' else
              '在 ST 与修改的槽位间随机切换，确认实时预览立即更新，再拍照并回放。单独外观写入无需接电脑另点核对；若名称阶段提示尚未写程序，请接回并点“继续槽位更改”。'
              if mode in ('install_all','look_import','slot_default') else
              '确认能正常取景，检查菜单／外观预览，并拍照、回放。若本页显示待核对，请接回 USB 后点击该页明确列出的核对按钮。')
    check_note='加载核对只读取状态，不会再刷一次。' if setup or (mode and mode.startswith('sound_')) else ''
    return STEPS + reason + '\n\n下一步：' + follow + '\n\n' + check_note + '点“确定”只关闭说明，不会自动断电或代替你确认测试。'
