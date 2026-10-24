# 像素偏移研究：开发分支

[首页](../../README.zh-CN.md) · [English](../en/pixel-shift.md)

有 A7CR 的机主可用[参考数据收集工具](cr-reference.md)提供原厂参考照片及可选的只读参数快照。

目标参照 A7CR 原生流程：三脚架、静态场景、四张位移 RAW，之后在电脑合成。十六张模式作为后续目标。公开程序属于**离线研究，不是可安装或已实现像素位移的正式版本**。

## 全量固件分析与外部线索

研究已纳入两份官方 2.01 固件的完整普通文件集合：A7CR 1198 个，C2 1196 个，各含 564 个 AArch64 ELF 程序／库。[完整提取](../../dev/pixelshift/extract_firmware_corpus.py)与 [ELF 索引](../../dev/pixelshift/index_elf_corpus.py)输出完整可执行节反汇编、跳转、符号、重定位、依赖、栈展开范围和 ASCII 候选字符串。两份 AP 的 `.text` 节均完整解码；其他可执行节仍有无法解码的字节。每个机型各有两个库的栈展开记录无法由当前解析器读取。这些缺口保留在私人报告中，节解码不代表间接调用或运行行为已全部解析。

先复制原有 Ghidra 工程，再执行全程序分析。[调度准备](../../dev/pixelshift/PrepareFullAnalysis.java)、[覆盖统计](../../dev/pixelshift/FullProgramAudit.java)和[完整索引](../../dev/pixelshift/FullProgramIndex.java)覆盖当前全部已识别指令、函数和引用，记录间接跳转、内存覆盖和分析超时。CP／控制器镜像分别使用正确架构与装载映射，不把原始镜像里的所有数据当成指令，也不把整份 Bonobo 容器按零地址导入。

外部截图用于提供线索，不能直接确定调用含义：

- Sony 四张流程采用一像素传感器位移，十六张流程还包含半像素位移；不能用“每帧必须半像素”统一判定。
- [原始 RTTI／调用链核对](../../dev/pixelshift/reset_semantics_audit.py)确认两机的 `sequence_set_program_shift_reset` 到达 `0x4043 / PID_SET_P_SHIFT_RESET`，`sequence_set_program_shift_drive` 到达 `0x401B`；实际 CP 命令表分别绑定复位标志与 `sc_PShiftDrive` 设置器／`CheckSetPShiftDrive`。这些都是 P 档程序曝光偏移命令，不是传感器像素位移命令，不能作为回中修复或位移标定的证据。
- 所列 P/Y 伺服名称同处一个诊断 CSV 表头。表头和 MECHA 不可用诊断均不能证明连续的标定结构、C2 缺少标定，或快门错误由 IBIS 超行程造成。精确定位也不要求必须开环控制。
- 机主提供的 PTP 数据现已完整解析：390 条属性、10426 字节，无重新定位或跳段。[离线解析器](../../dev/pixelshift/sony_property_dump.py)支持范围、数组、字符串和 Sony 第二份枚举。`0xD25F` 是**变焦设置**，已用原始 AP 的属性名称／编号路径独立确认；三值枚举不等于像素位移。该份数据未列出已知像素位移属性 `D239–D23D`、`D2D3`、`D2D4`。这是对所提供文件的结论，不是新一次实机连接验证。

本轮没有新增相机访问或实机候选。继续追踪 CR 真正的定位、完成／取消、归位和曝光依赖，再逐条对照 C2。

机主补充了 CP 单元实读与配置分析工具。复用其中的离线名称表解析器，可重现 C2／CR 的设置编号 `652`、启动禁止键 `4191`；配置解析方法也找到两机 CP DmmCfg 中相同的像素位移状态／设置记录。不必重新提取或猜测新增这些记录，但其载荷尚不是已确定的位移值。

- [原生备份缓冲区读取](../../dev/pixelshift/cp_shadow_load_replay.py)：16 组配对案例执行原始 20 项表初始化，以及完整的单项／全部读取包装层、BK4 查表和 ARM 复制。19 个单元进入各机型自己的原生目标缓冲区；未知编号保留原生错误，单项读取保持其他缓冲区不变，输入库不变。测试覆盖官方库，以及仅在模拟输入里替换的 256 字节 `0x02A4000B` 合成数据；私人实读也已单独通过该路径。尚未执行回调注册和完整启动，仅省略读取器原有的无返回值互斥边界，不连接相机或执行持久化 API。
- [九点来源与图像采样](../../dev/pixelshift/cp_grid_source_replay.py)：24 组配对案例执行原生坐标缩放、尺寸表选择、运行结构／单元缓冲区写入，以及单独调用的原生图像采样函数。生成的九组坐标随图像尺寸变化，写入 `0x02A4000B` 的缓冲区；其中一个原生生成坐标索引合成图像缓冲区的四字节数据。生产函数停在备份写入 API 之前，没有伪造该调用成功。这确定了一条图像坐标产生／采样用途，不能据此解释整个单元，更不能把它直接当作执行器位移标定。

两机 AP／CP 和 CR 控制器工程的私人全程序 Ghidra 索引现已产出。CR AP 此轮达到分析时间上限，C2 AP 与两份 CP 未超时；两侧原有种子历史不同，且仍有解码／间接调用缺口，函数数量不能直接当成功能缺失数量。H8 解码仍为有限范围支持，索引产出不代表完整固件或物理行为已执行。

启动序列的禁止键有十六条输入规则，与设置项的十条不同；`FUNC_start_px_shift_multi_shoot_seq` 本身不是 PTP 操作码。新增八组 [CAIF 帧测试](../../dev/pixelshift/cp_caif_frame_replay.py)执行原生 SDK／工作线程片段／环形队列，保留完整 34 字节帧。独立 GPIO 输入选择原生分支；读取帧头的案例停在总线驱动之前，保留有效的八字节读取描述符和仍在队列中的负载，不伪造对端响应、负载传输、稳定到位或曝光完成。

[原生缓存采集](../../dev/pixelshift/cp_scale_acquisition_replay.py)现已把原始双通道缓存运算片段、完整记录回调，与既有尺度计算、完整控制／向量生成及两种封包格式接在同一份模拟 RAM 中。八组两机对照覆盖一／二／四组样本、不同基线、零差值和负差值，之后执行 32 个向量步骤。测量记录的每个样本半字均由原始回调写入，写入游标也由原生代码推进。测试提供独立缓存原始字、系数输入和采集分支选择，分别调用各阶段，不直接写样本数组或计算后的尺度，保留原生错误行为。此续接还执行原始本地控制记录更新、脚本索引推进和函数返回，先核对实际栈及受保护的核心／VFP 寄存器，再由测试恢复单独暂停的调用方上下文。本地 CP 记录更新不等于硬件通知。尚未执行原始外设采集、完整调整脚本、自动调度、实际定位／稳定或曝光。静态分析找到的更上游读取器／快照复制，也不直接当作已经验证的传感器反馈；既有局部计算测试保留原边界。

[原生输入来源发布](../../dev/pixelshift/cp_input_source_replay.py)新增 64 组两机对照，从原始寄存器读取器和来源选择器，经过实际定点缓存、帧字段、完整 340 字节快照复制，到采集侧读取函数。案例覆盖来源有无、选择开关、行形状、边界策略及独立的可用状态返回值。13／14 位掩码及 Q12 转换均由原生代码执行；测试不直接写选中的结果或复制后的快照。寄存器地址与数值是合成输入，并非已验证的相机 MMIO 映射；尚未执行完整缓存更新调用方及后端初始化。这些字段与数值本身不能证明实际传感器位置反馈。

[原生上下文至输入绑定](../../dev/pixelshift/cp_context_source_replay.py)在输入来源测试之前新增 16 组两机对照。完整原始句柄区复制及上下文初始化函数，现在负责生成读取器使用的子对象指针和两路寄存器基址；测试只提供源端句柄及辅助指针。核对全部 924 字节句柄区，包括 100 个句柄条目及保留的首字，并以独立指针运算核对全部 200 字节上下文。源区及相邻标记保持原样，原生函数完整返回并保留栈与受保护寄存器。生成的绑定在同一 RAM 中进入原始选择器、缓存、完整快照复制及读取函数，消除了这些目标绑定的主机赋值，但尚未执行后端创建、真实寄存器映射或完整流水线调度。静态追踪还区分了配置对象与读取对象所在的槽位：共同使用 `BBxx` 偏移，本身不能证明两者访问相同硬件或提供位置反馈。

上下文测试还核对两机原始构造函数的写入位置及虚表／RTTI 链：读取槽使用 `Camera::CamCore::DevEdgeGetter`，配置槽使用 `DevEdgeSetter`。构造函数仅被检查，没有执行。这些名称确定了原生接口类型，不能证明其数值是 IBIS 位置、具有何种物理单位，或正常拍摄必须先运行这段校准。此调整输入路径仍须与尚未验证的定位／稳定／曝光闭环区分。

[原生设备描述符绑定](../../dev/pixelshift/cp_device_binding_replay.py)在上下文／输入链之前新增 64 组两机对照。完整原始分通道绑定函数读取描述符中的可选边缘设备字段，为每个启用通道生成十四个读取句柄及一个辅助指针，再经过原始辅助函数和函数尾部返回。测试核对全部 924 字节读取接口区、准确写入顺序、源数据保留、栈及受保护寄存器；描述符为空或边缘接口缺失时，保留原生不写入行为。生成的句柄在同一 RAM 中继续经过原始句柄复制、上下文装配和完整输入快照，主机不填充这些中间输出句柄。设备描述符及寄存器回应仍是独立合成输入。静态调用方追踪区分了这条读取路径与硬编码配置基址函数，没有把两者相接。设备发现、虚拟能力调用、自动流水线调度及实际位置反馈仍未执行。

[原生设备取得](../../dev/pixelshift/cp_device_acquire_replay.py)在两机上沿 CR 原始路径执行：初始化八对象池、取得／释放实际原子锁、取出对象、执行完整构造函数及 ARM 清零函数，再通过构造函数生成的虚表进入原始初始化。36 组对照覆盖任务／中断上下文、三种请求类型及有效／无效通道；非零测试数据确认原生代码清除了 2,790 字节，非法通道保留错误 `0x10004`，不消耗对象池。启用原始后端构造后，同一请求继续经过公共资源准入，到达两个寄存器写入初始化入口之一；测试停在入口之前，没有注入成功返回。此时尚未执行后端地址绑定，看到零基址只代表初始化不完整，不能当作相机缺少标定的证据。这些选定的设备取得路径在 C2 中本来就存在；两机一致不代表像素位移拍摄链已完整。取得的对象也没有被当作初始化成功，直接交给前面的合成读取测试。

[原始启动配置](../../dev/pixelshift/cp_startup_config_replay.py)现在执行各机型完整成像器构造函数、原生单例绑定及真实虚拟查询，包括原始 116 字节复制。四组两机对照覆盖以显式 `0xff` 覆盖哨兵选择构造默认值，以及另外的覆盖输入。C2 与 CR 有 15 个配置字节不同；C2 保留自己的构造值，没有接收整块 CR 配置。初始 BSS／填充字节及覆盖开关仍是测试输入，不能据此断言实机开机后的有效配置。

[配置至地址绑定](../../dev/pixelshift/cp_startup_binding_replay.py)将原生查询输出直接交给同一 RAM 中的原始后端构造及地址绑定前段。四组两机对照覆盖两种覆盖参数，以及零／非零寄存器初值。原生代码执行 57 次寄存器写入，另用独立掩码和配置运算核对六个寄存器字。寄存器窗口只是模拟器普通 RAM，没有编造外设行为。测试明确将 IRQ 编号范围设为零，原生 IRQ 启用 API 因此对 `0xa2` 返回 `-17`；原始调用方继续执行，但这不代表中断设置成功。执行停在首次创建 DMA 对象之前，地址绑定调用尚未返回。DMA 构造、完整启动、硬件就绪、位移和曝光仍未解决。

加上 `--continue-dma` 后，[同一启动测试](../../dev/pixelshift/cp_startup_binding_replay.py)现已执行完整原始五对象 DMA 构造，再返回仍在运行的地址绑定调用方。新增四组两机对照核对五份原生记录、21 个描述符、20 个 DMA 寄存器字及五个路由掩码字；路由指针及四位字段位置来自各机型原始映像，构造函数保留实际调用栈与受保护寄存器。之后执行到一处控制初始化循环：原生代码置位后读取 `0xF3830810`，等待掩码 `0x10001` 清零。测试停在再次循环之前，保留未完成值。普通寄存器 RAM 没有对应硬件变化模型，测试没有补出确认信号。附近原始诊断将该公共图像处理块称为 PFR，并检查图像宽度；尚未证明该寄存器表示传感器位置或稳定完成。后续移植应回到 TRINITY 拍摄前提，不将完整仿真公共开机硬件作为必要条件。地址绑定调用仍未返回，没有模拟 DMA 数据传输、曝光或完整启动。不加此选项仍可重现先前停在 DMA 构造之前的边界。

[原生拍摄条件调用链](../../dev/pixelshift/cp_capture_gate_replay.py)现在以原始资格判断函数和调用方后段，替代测试直接提供的 `+0xD88` 标志。在 AP 生成的 TRINITY 命令完成原生分派后，同一 RAM 中的原生代码分类源拍摄模式、读取覆盖及流水线状态，把结果传给完整快照函数，由其写入标志并返回调用方；真实拍摄配置读取函数再提供模式选择器所用指针，最后执行原始 TRINITY 一致性策略。96 组两机对照一致：TRINITY 关闭时该标志仍可成立，说明它是共用拍摄条件；传入的 TRINITY 值 1 只有在选中模式 `0x17` 时保留。策略清除不兼容模式时仅略过一个诊断打印调用，原生代码随后覆盖其返回寄存器，没有注入 API 成功值。源模式、流水线状态、覆盖开关、保护状态及调用时机仍为测试输入，完整外层调用／调度和这些输入的真实生产者尚未解决。单独的 `0x9416` 数据块写入没有被当成实时配置来源。

[原生拍摄上下文发布](../../dev/pixelshift/cp_capture_context_replay.py)在拍摄条件判断之前新增 192 组两机对照。完整原始上下文装配函数写入所用流水线指针，独立执行的原始读取函数确认是同一对象；原始 `EnterCapturingLv`／`ExitCapturingLv` 函数负责写入选择器保护状态，覆盖反复进入／退出，正常返回并保留栈及受保护寄存器。主机不再赋值这两个中间结果。`CapturingLv` 仅是原始函数标签，未被解释为防抖模式。流水线数据、辅助指针、生命周期顺序及调用时机仍是测试输入；尚未执行完整启动、自动调度、实际定位或曝光。

[原生流水线条件来源](../../dev/pixelshift/cp_pipeline_source_replay.py)新增 492 组两机对照。原始调用方片段计算禁止参数，完整原始状态生成函数连同 GPIO 读取器计算源条件；原始配置片段将条件及相邻策略字段写入已绑定的流水线，再经过原生快照、模式选择及 TRINITY 策略。测试保留原生旧值保留分支，包括输入禁用时不改写策略字；相邻字段还能独立使源模式 33 转为模式 1。两机调用参数及对象身份均按原始代码核对。本测试只执行生成器分支 3；GPIO 映射／寄存器值、配置、通知历史／旧状态及阶段／寄存器绑定仍是测试输入，未执行完整配置函数或自动调度。GPIO 数值尚不是已验证的传感器位置或稳定到位应答。

[原生拍摄请求](../../dev/pixelshift/cp_capture_request_replay.py)新增 96 组两机对照。原始快照调用方现在从入口执行到返回，包括拍摄管理器初始化及完整原生快照，核对准确头部、栈及受保护寄存器；三次记录／日志传输调用被记录后省略，这些依赖尚未执行。之后单独调用原始客户端，由其构造拍摄回调记录，进入完整原生发送器，经原始消息缓冲区发送／接收及工作线程调用器，进入实际拍摄函数并到达模式选择。普通及跨尾回绕两种队列位置均保留同一份 28 字节请求，主机不赋值回调指针、发送成功值或接收负载。客户端另一次记录传输被省略。工作线程停在拍摄回调内部，两者均未返回；之后的 TRINITY 一致性仍单独调用。线程交接、客户端调用及 OS／队列／调试／配置状态仍是测试输入；外层拍摄准入处理器、自动调度、实际定位、稳定及曝光尚未打通。

[完整原生采样回调](../../dev/pixelshift/cp_sample_stage_replay.py)在同一 RAM 中续接八个原始准备／平均阶段。12 组两机对照覆盖两种输入来源，采样次数为零／一／三，其中零由原生代码解释为两次。样本计数重置／累计、双精度求和、平均值保存及阶段／脚本索引推进，均由原生代码完成；完整返回保留实际栈及受保护的核心／VFP 寄存器。六组明确绕过校准校验，以单独检查平均运算；另六组保留校验，合成的恒定输入最终得到原生错误 `0x0505`，没有进入校验通过的缓存状态。因此，八阶段跑完并不代表校准成功。此测试尚未把这些平均值接入下游采集／尺度计算，也未执行完整调整调度器或证明实际反馈、定位、稳定及曝光。

10 月 20 日，两次经机主授权的三字节 RAM 测试均出现菜单，但功能仍被禁止。第二次已装 SD 卡并使用静态 P/M，因此不能把失败归因于缺卡。两次修改都已还原并独立核对，没有拍摄。

继续反汇编后，找到 C2 另一张参数能力表中的未定义项；原生初始化会为此加入四个禁止计数，与实机唯读结果吻合。已解析十条正常排他规则，在当时静态 M、空闲状态下均未触发。第三次私人测试补入 C2 原生参数定义，并只撤掉这四个“参数未定义”禁止计数，同时开启菜单：六处 AP 数据窗口，共 47 字节。独立读回通过，但机主在关机之前进入了空的子菜单。之后唯读检查确认六处均回到原值，无须再写入还原；没有拍摄。

子菜单各选项还有独立的机型支持表。第四次 RAM 测试只增加“关／四张”支持：共八处窗口、51 字节，十六张仍隐藏。读回通过，但机主反馈图标缺失，后来出现相机错误和黑屏。断电后临时表恢复，原生“四张”设置却仍保存在备份中；没有报告拍摄。机主随后自行救回相机，具体方法未记录。后续独立读取确认运行模式、RAM Backup、已保存 Backup 均为 OFF，机主也确认拔线后正常取景 30 秒。候选仍撤回，这不代表像素位移或长期硬件验证成功。试验没有修改 ROM、CP 或校准，但原生菜单确实保存了设置；此处不分发私人实机工具。

## 已实现

- [调用链检查](../../dev/pixelshift/audit.py)：从私人提取的 C2／A7CR 2.01 程序解析像素位移序列的 RTTI 和实际虚函数，核对“序列 → 包装层 → 通用拍摄封包构造”，定位像素位移函数名称的代码引用。
- [原始指令重放](../../dev/pixelshift/native_replay.py)：四／十六张及间隔选择的 18 组对照一致；触发命令 `0x4036` 的 44 组封包对照一致。另有 24 组核对真正的捕获启动命令 `0x4038`，其六种输入枚举分别映射到不同的传输值。选择测试停在蓝牙反馈配置前；`0x4036` 封包省略一次诊断调用，`0x4038` 省略两次，均在发送前停止。无效捕获枚举离开限定模型时不会得到成功封包，没有执行 CP 放行、曝光或定位。
- [原生模式设置](../../dev/pixelshift/trinity_replay.py)：固件内部称像素位移为 `TRINITY`。原生命令 `0x40ee` 及 CP 模式赋值的 20 组对照一致，涵盖关闭、四／十六张、间隔及原生测试标记。CP 片段只赋值模式，不代表已驱动传感器。
- [CP 命令分派](../../dev/pixelshift/cp_dispatch_replay.py)：80 组对照以 AP 原生生成的 `0x40ee` 封包执行原始查表、可选一致性回调、模式处理和参数更新标志设置。初始 RAM 与待检查字段为合成状态，只省略诊断打印，没有执行传输、CP 调度或拍摄。
- [CP 配置快照](../../dev/pixelshift/cp_config_replay.py)：八组对照在同一份模拟 RAM 中，将上述原生处理器写入的模式交给原始快照函数及 ARM `memcpy`，3428 个复制字节全部一致。LiRo 的 `+0x180` 落到拍摄配置 `+0x1a0`，测试没有再次给模式赋值。其他输入字段和快照参数为合成数据，两处入口之间的调度未执行。
- [当前设置到 TC 输入](../../dev/pixelshift/cp_mode_source_replay.py)：六组对照把已分派的模式，经原生 3428 字节当前设置复制、指针注册表初始化、TC 旗标更新、完整 340 字节输入复制、导出及 192 字节发布／快照继续传递。旗标不靠测试中途重新赋值模式产生。AP 选择值 1／2 均编码为 CP 开启值 1。无关设置／上下文为合成数据，设置复制从信号量准入之后开始，任务调度／延迟通知未执行。这确认另一条旗标来源，不代表每组拍摄已正确收尾。
- [CP 帧内传递](../../dev/pixelshift/cp_frame_replay.py)：24 组对照在同一份 RAM 中继续执行原始帧映射，将模式送到 frame `+0x98`，再经过后续控制旗标设置及请求选择片段。设置器读取的 `+0x78` 来自 frame 的 `+0x20` 视图，基址关系已核对。准备阶段的条件与其余字段未执行或采用合成输入；后续请求覆盖与传输未执行，不能把选出的数值认作已识别的位移命令。
- [CP 串行字段传递](../../dev/pixelshift/cp_serial_replay.py)：56 组对照把合成帧的 TRINITY 标志与张序号，经原始 TC 输入／复制／序号片段、原生编码、串行缓冲区填入及校验计算，送到 `0x39` 封包的 `0x6e` 字节，其值为 `(张序号 & 127) | (TRINITY << 7)`。原生接口模式初始化决定是否填入扩展区，另一个标志决定发送描述符使用 100 或 128 字节。测试在同一份 RAM 中执行普通 TC 分支，其余负载字段和接口输入为合成数据；完整 TC 运算、调度、串行传输、物理接收方及位移仍未验证。
- [原生默认参数加载](../../dev/pixelshift/cp_defaults_replay.py)：两组官方参数库对照执行原始 BK4 注册、两项配置查询、完整 256 字节参数复制、接口解码及 TC 分支选择。两机型都加载接口字 `0x0066`，解码为类型 6；后续配置不覆盖时会选择另一条 TC 分支。只省略五次无返回值的互斥锁调用。这修正了上一项的适用范围：合成输入下的普通分支尚不能当成相机实际使用的分支。
- [默认选择的替代 TC 分支](../../dev/pixelshift/cp_alternate_replay.py)：八组、每组四步的配对序列，在同一份 RAM 保留原生默认选择，经过原始入口进入替代函数，再发布／读取两个 32 字节缓冲区。原始代码完整保留序号、更新计数及辅助字。输入、共享旗标和调度为合成状态；刻意使用无效 GPIO 埠，让原生检查在硬件访问之前拒绝。它验证软件传递，不是可用的 GPIO 配置、实际协议或物理位移。
- [原生序号到向量运算](../../dev/pixelshift/cp_vector_replay.py)：12 组配对步骤在上述 RAM 继续执行原始帧旗标导出、192 字节发布／快照复制，以及由 TRINITY 旗标控制的向量运算。序号 0–3 产生四步原始图样，再乘上参数 `0x000f0025` 中的三个比例字节。两机型官方参数库加载的三字节均为零；另用非零比例及指数做合成敏感性检查。这个有条件的运算片段不包含之前的模式选择、完整调度、传输或驱动。物理单位及实际运行时比例来源仍未明确，不提供比例值刷写方案。
- [替代分支封包／回覆校验](../../dev/pixelshift/cp_alternate_wire_replay.py)：八组配对案例把上述向量继续送过完整原始 40 字节封包构造器及原生 XOR 校验。向量保留在第 4／8／12 字节，TRINITY 在第 28 字节。24 组配对回覆案例验证原始类型／校验分支及完整接收快照复制，包括拒绝错误资料时不改动已接受缓冲区。回覆是独立注入的合成输入；没有验证实际传输、硬件确认、稳定、曝光或归位。
- [替代分支两阶段封包](../../dev/pixelshift/cp_phase_pair_replay.py)：八组对照加载原生出厂格式配置，先执行原始 type 7 构造／校验，再执行既有 type 8 构造。另八组 `--full-control` 案例先在同一 RAM 执行原生消费者和完整向量生成器；两个构造器均不替换生成的向量或帧快照。两个 40 字节包均符合原生 XOR 约定。阶段由测试调用，无关输入为合成数据；没有执行实际传输或控制器反馈。
- [控制器参数封包](../../dev/pixelshift/cp_parameter_wire_replay.py)：六组配对参数字执行参数 `0x170006` 的官方数据加载、原生缓存差异扫描、第一阶段构造及校验。三个四字节参数字携带偏移 `0x60/0x64/0x6c` 的系数及偏置。分别测试默认值与独立非零敏感度输入；旧缓存差异为合成状态。可选 H8 重放校验这些包，执行完整原生参数命令、检查精确写入，再对仿真寄存器执行系数／控制字存储和偏置使用。前面的 GPIO 配置、实机调整数据和物理配置尚未确认。
- [原生尺度计算](../../dev/pixelshift/cp_scale_calculation_replay.py)：十组配对案例执行原始测量指针初始化、调整运算及 72 字节诊断记录。计算出的三个尺度字节留在同一 RAM，进入完整原生消费者、向量生成器及两阶段封包构造，共 40 组配对步骤。独立有理数计算核对零／负分母、上界和字节舍入。测量输入及命令准入状态为合成数据；执行停在通知之前，测试框架在此恢复 CPU 寄存器。这是调整脚本的计算，尚未证明是正常拍摄初始化或机身标定；尺度字节没有由主机赋值。
- [Bonobo 控制器桥接](../../dev/pixelshift/BonoboBridgeReplay.java)：可选 Ghidra H8 重放读取上述实际 CP 包对，执行控制器的类型／校验／接收缓冲区选择前段、原始字段读取、TRINITY 分支及目标寄存器写入。独立于 Python 测试，共通过 16 组缓冲区／封包案例及 32 次损坏校验进入错误边界的检查。寄存器写到仿真内存，未模拟 ADC、DSP／PWM、马达、完整中断／启动或真实到位。这是原生代码的协议匹配，不是实测位移、实际接线或标定证明。
- [控制器回覆到 CP](../../dev/pixelshift/cp_controller_reply_replay.py)：原始 H8 取样／编码从独立提供的仿真寄存器输入产生回覆。16 份负载在两机型上通过原生 CP 类型／校验、完整复制、解码及有符号读取；损坏校验进入拒绝路径。回传字为输入 32 位元寄存器值的有符号高 16 位元。测试回传输入独立于目标值，主机不修补负载。外设值和帧头仍为合成数据；接收端重放没有执行命令／反馈时序，也未验证实际位置。
- [替代分支反馈解码](../../dev/pixelshift/cp_feedback_replay.py)：24 组对照在同一份仿真 RAM 中，从已接受回覆继续执行其原生解码器和有符号读取器。回覆第 4／6／8 字节的三个半字得到保留，另执行独立的 16 字节上下文／历史复制及 20 项环形缓冲区回绕。历史输入为合成数据。此路径与第一阶段反馈解码器读取的缓冲区不同；读到数值不等于已识别传感器位置或到位反馈。
- [Darwin 接收／解析重放](../../dev/pixelshift/darwin_capture_replay.py)：276 组对照执行原始消息查询、34 字节 RX 到稳定缓冲区的复制、快照获取及解析前段。覆盖每个输入位元，核对完整快照及状态写入范围。RX 和初始状态为合成数据；没有替代外部调用，停在后续控制调用之前。串行接收、完整 CP 到 Darwin 衔接、驱动控制及传感器位移尚未验证。
- [CP 逐张选择](../../dev/pixelshift/cp_sequence_replay.py)：64 组对照执行原始状态字节读取、序列选择及 17 项描述符初始化。在模式 23 下，四个帧序号都选择首列序列；普通模式 2 则能选择后续帧列。测试停在序列配置之前，没有执行选中的回调、曝光或定位。
- [CP 回调阶段分派](../../dev/pixelshift/cp_stage_replay.py)：19 组对照以合成上下文阶段分别调用这两个回调，执行原始跳转表，停在选中子处理器之前。核对七／八个有效阶段及原生无效阶段返回值。它建立处理器顺序；调度器没有推进阶段，也没有子处理器执行曝光或归位。
- [已注册回调／CAIF GPIO 路径](../../dev/pixelshift/cp_caif_gpio_replay.py)：八组配对案例从各官方默认参数库读取 12 项真实参数，两机型均配置 GPIO 11／26、11／25。独立调用原生来源所注册的回调，先置位事件 `0x35/0x10000`，再执行控制动作。在初始化后选择器片段的普通调试输入下，原生 SDK 分配／发送／接收、工作线程复制／释放及分派把 type-12 请求送到 11／26 的 GPIO 清除寄存器写入；调试选中的直接路径则写 11／25，另以回调跳过输入作负对照。主机不向接收者复制队列字节，外设输入值也不随命令伪造更新。事件在队列被消费前就已置位，不能作为 GPIO 完成或传感器稳定应答。省略 BK 读取器互斥锁及两次回调／动作诊断调用；端点／内存池／OS／调试／MMIO 状态与线程边界为测试输入。后台初始化、客户端注册、工作线程统计过渡、完整工作循环、物理接线／位移及曝光同步尚未验证；有效动作停在后续追踪消息构造前。
- [完整原生控制向量](../../dev/pixelshift/cp_control_replay.py)：八组逐张对照执行实际替代控制状态机和完整向量函数，保留前次向量状态，不预先填入计算结果。另三块出厂参数经原生代码加载，其余初始 RAM 和帧输入为合成数据。六组由测试选择调用顺序的后续控制请求表明，category 4／5／0 本身仍保留最后的 TRINITY 向量；两组明确送入下一帧 OFF 的案例改用独立提供的合成兜底目标值。空闲发布停在 GPIO 调用之前。自动完成／取消、归位及物理位移仍未验证。
- [稳定定时／等待事件](../../dev/pixelshift/cp_steady_event_replay.py)：八组对照执行原生资格判断、定时回调、原始 ARM 中断上下文判断及拍摄等待前段。回调和等待端使用同一事件 `0x2e`、遮罩 `0x80000000`，限时等待收到参数 10000。上下文／帧输入为合成数据；回调与等待端分别调用，停在 RTOS 事件 API 之前，没有真实定时触发、等待完成或到位确认。
- [拍摄状态检查](../../dev/pixelshift/capture_gate_replay.py)：102 组对照执行原始 `0x4040` 请求编码、CP 有效遮罩与回覆字段形成、AP 解码，以及 `REQUEST_CAPTURE`／`CAPTURE_NG` 事件分支。回覆字节由电脑端桥接，未执行传输、CP 状态刷新、回覆分配或事件分派；状态输入为合成数据。这层软件检查通过不代表传感器定位就绪或拍摄成功。
- [CP 触发路由](../../dev/pixelshift/cp_trigger_replay.py)：72 组对照执行原生 AF／AE／AWB 优先级初始化与仲裁、触发消息转换，以及选定的内部消息路由。AF 准备分支停在辅助函数之前，捕获开始分支停在处理函数之前；AWBL 开／关执行原始旗标设置。注册表、前一触发值和内部对象为合成状态；未执行发送器本体、分配、传输或对象调度。这些测试区分准备／锁定与捕获，不模拟曝光成功。
- [序列／清除边界重放](../../dev/pixelshift/lifecycle_replay.py)：22 组对照核对原生拍摄序列建立请求、排队开关、`0x40ef` 清除封包，以及指向 `TrinityShotEnd` 的 CP 回调描述。两台分别使用自己的管理器地址。明确使用合成状态并省略互斥锁／诊断调用，停在分配、构造、传输或清除服务之前；尚未验证回调完成或传感器归位。
- [原生拍摄组结束／释放](../../dev/pixelshift/cp_group_end_replay.py)：14 组基线停在资源／对象池／回调边界；七组 `--full-pool` 执行空资源回收／内核恢复。四组 `--native-completion` 增加原生来源回调／事件产生，仍有队列测试边界。另四组 `--native-queue` 通过完整原生发送器、实际队列 API 和两轮原生工作线程消除该边界，并保留独立暂停的工作线程栈。组结束仍由测试框架在边界调用。真实拍摄资源、等待任务接收、底层分配删除、真实任务／多核调度和物理归位尚未验证。
- [原生引用锁 API](../../dev/pixelshift/cp_native_lock_replay.py)：16 组配对案例在合成 OS 状态上执行原始 ARM `LDREX/STREX`、持有者更新及释放／屏障。无竞争的任务／IRQ 路径可完成；错误上下文、中断屏蔽、非法编号和错误持有者保留原生错误。锁忙碌时停在 `WFE` 前，不提供唤醒结果。这是在单个仿真核心验证软件行为，尚未运行真实相机调度器。
- [对象池范围／回收子路径](../../dev/pixelshift/cp_pool_recycle_replay.py)：12 组配对案例以实际执行的锁 API 验证原生范围检查和空闲链表更新。有效且未屏蔽中断的输入会更新链接与空闲计数；越界／空指针被拒绝。中断屏蔽时，内层回收失败，外层范围检查却仍返回 1，因此报告另行核对链表／计数。对象池和 OS 数据为合成状态，外层完整回收／资源封装及拍摄组完成仍未执行。
- [原生入口互斥锁／上下文恢复](../../dev/pixelshift/cp_native_mutex_replay.py)：14 组配对案例执行原始入口互斥锁、持有者／错误逻辑及内核调度器的同任务核心／浮点上下文保存恢复。不同浮点寄存器值无需主机恢复即可保留。错误上下文、中断屏蔽、禁止调度、非法编号和重入保留原生错误；竞争持有者停在入队前，内核锁忙碌停在 `WFE` 前。任务／OS 状态为合成数据，没有切换到其他任务。
- [完整外层对象池回收](../../dev/pixelshift/cp_pool_return_replay.py)：七组配对案例执行原始外层互斥锁、带锁校验的回收、对象池记录及原生锁释放／同任务调度。未退役的测试描述符避免底层分配删除。对象有无回收，函数都可能返回 0，因此分别核对精确链接／计数和内层 API 状态。错误准入案例是合成测试，不代表相机曾处于这些状态。竞争持有者停在等待前；本独立重放不含实际资源或拍摄组完成。
- [原生完成注册／事件](../../dev/pixelshift/cp_completion_replay.py)：七组配对案例执行原始客户端一个分支的可调用记录、原生发送前段及出队后分发／调用／注册代码。发送器产生的原样 28 字节消息跨过明确的合成队列边界，没有执行收发 API 或完整发送／工作线程循环。所选回调通过原始 RTOS 代码更新事件 `0x35`、标志 `0x10000`，保留原事件位及无关的开始回调。测试延迟／标记已置位状态、拒绝上下文和内核锁忙碌；其检查的单次标记是下述 PowerOffDetect 旗标。空等待队列不能证明拍摄任务已收到通知；此完成事件与稳定计时事件 `0x2e` 不同，其他原生回调／动作变体尚未执行。
- [原生工作线程消息缓冲](../../dev/pixelshift/cp_actor_queue_replay.py)：12 组配对案例执行原始收发、环形缓冲头、FIFO、对齐、绕回及 ARM `memcpy`。满／空轮询、非法尺寸／编号／上下文／超时、禁止调度及锁竞争保留原生行为，阻塞转换停在等待前。队列／任务配置为合成状态，主机不向接收端复制数据或提供 API 返回值。
- [客户端／队列／工作线程传递](../../dev/pixelshift/cp_actor_delivery_replay.py)：六组配对案例执行两个完整发送器及两轮原始接收／分发，包括绕回和延迟／即时完成注册。实际接收器得到原生发送器的相同字节，队列恢复为空及完整容量。原始性能记录开关代码执行，测试输入禁用记录。工作线程在第三次接收前暂停、不返回，并使用独立栈区域。参与线程的边界仍由测试框架调用，没有真实任务间调度或等待拍摄任务接收；所选客户端分支的准入仍是合成输入。
- [原生清除／结束入队](../../dev/pixelshift/cp_queued_end_replay.py)：六组配对案例先构造对象，再执行原始 CP `0x40ef` 处理器、完整发送器及工作线程实际接收的第三条消息。工作线程调用 `TrinityShotEnd`，测试框架不跳转到结束函数或恢复通用／浮点寄存器值。核对精确可调用记录、原生被调用者寄存器保留、队列所有权、空资源对象池回收和事件产生，并覆盖清除记录绕回。带资源句柄时停在释放前，消息仍在处理中，不能用“队列已空”判定完成。另六组 `--consume-completion` 在同一 RAM 执行原生事件消费者；再六组 `--ap-dispatch --consume-completion` 先运行原生 AP 清除封包构造和 CP 命令表分派器，未经修改的封包跨越明确的主机字节传递边界。参与线程的栈边界及 OS／对象池数据是合成状态，AP 到 CP 硬件传输、真实任务切换、拍摄资源完成及物理归位尚未验证。
- [捕获线程完成事件查询](../../dev/pixelshift/cp_completion_consumer_replay.py)：九组配对案例执行原生事件查询 API、帧状态更新及分类函数。事件位 `0x10000` 优先于 `0x8000`；恢复位 `0x2000` 在恢复操作前停止，帧中已有状态位保留。错误上下文、IRQ 屏蔽及内核忙碌保留原生拒绝／等待边界。这是事件查询，不是阻塞等待或任务已被唤醒的证据；分类枚举不代表硬件就绪，也未执行捕获线程剩余部分。
- [关机检查请求边界](../../dev/pixelshift/cp_poweroff_replay.py)：三组配对案例执行原生单次前缀。原生日志明确命名 `PowerOffDetect()/offFactor`，命令 `0x4077` 将其排队执行，纠正了此前“拍摄停止／AP 通知”的解释。标记在分配前就被置位，不代表曝光完成或传感器稳定。已有标记时原生返回；另以独立的分配后缓冲区测试输入执行来源头及 16 字节本地查询构造，此基线不执行分配、发送或回调。分组结束标记是另一个字段，保持不变。
- [原生关机查询分配](../../dev/pixelshift/cp_poweroff_allocate_replay.py)：四组配对案例消除上述预先提供缓冲区的缺口，执行原生端点查询、分配器、内存池拆分／摘除、锁、IRQ／调度保护及请求构造。成功路径准确占用 128 字节并保留一个已分配缓冲区；池耗尽／锁争用停在等待或背压前。端点／内存池／OS 配置及保护逻辑使用的计时寄存器仍为合成输入，此独立基线停在本地发送前，不执行启动注册或查询送达。
- [本地关机查询／回复／释放](../../dev/pixelshift/cp_poweroff_request_replay.py)：九组配对案例执行原生初始化前缀、接收者分配／注册、本地 `0x845` 路由及其真实缓存回调。请求 `0x00920162` 被原位改写为 16 字节缓存内容，随后缓冲区被释放并合并回内存池。七组非零缓存输入经过独立原生写入片段，完整的来信解析器未执行。缓存 `offFactor` 为 `0x81／0x84／0x85／0x94` 时会进入额外消息路径，执行在发送前停止；其余停在诊断前。接收者分配失败时保留原生注册／发送错误，仍正确释放请求。端点树、内存池／OS／计时寄存器及可选缓存输入仍为合成数据；这不是 AP 送达、硬件应答、后续回调或完整关机检查流程的证明。
- [CP 元数据重放](../../dev/pixelshift/cp_metadata_replay.py)：63 组对照核对分组编号、张序号及总张数的原生写入，输出是预先分配的六字节 `PixelShiftInfo`。输入帧状态为合成数据，没有模拟传感器。
- [CP 拍摄模式重放](../../dev/pixelshift/cp_capture_replay.py)：63 组对照执行原始配置选择及 TRINITY 一致性检查。给定原生配置字节 `0xd88` 后，模式 2 可转为模式 23；合成的原生状态字节能阻止转换。选中的模式不兼容时，程序会关闭 TRINITY。没有执行拍摄或驱动调用，AP 到该配置字节的完整来源仍待确认。
- [CP 定时重放](../../dev/pixelshift/cp_timing_replay.py)：八组对照追踪 `SetSteadyCapTimer`，停在创建定时器之前。请求延迟为曝光偏移减去 9000 微秒，低于该边界时用一微秒；回调名为 `eventCallback_End_Wait_StartSteadyCap`。这证明了一条按时间调度的路径，不代表传感器位置确认；没有执行定时器／事件 API。
- [能力表重放](../../dev/pixelshift/capability_replay.py)：52 组对照执行原生机型映射和表项读取。C2 机型输入 16 对应第 9 列，相关像素位移支持值原为关闭；模拟中修改两字节可开启这个标志。测试不包含运行中的能力缓存或硬件，不生成刷写文件，也不按数字猜测 A7CR 的机型身份。
- [各选项支持重放](../../dev/pixelshift/option_replay.py)：78 组对照执行原生机型对应的子选项显示判断。子表字段偏移与父表不同，而且必须恰好为 1。C2 的三项原本均隐藏；模拟中只开启“关／四张”后，两项可通过这层判断，十六张继续隐藏。没有执行运行时权限、缓存、菜单绘制或拍摄。
- [参数资格重放](../../dev/pixelshift/eligibility_replay.py)：新增 26 组原始指令案例，区分菜单支持、参数是否定义及数值是否可接受。C2 的宽松兜底函数接受数值，不代表功能已定义；A7CR 定义了关／四张／十六张。用合成注册表执行 C2 原始初始化，记录到四个禁止通知；模拟补入原生定义后不再产生这些请求。通知函数只观察、不执行。另解析十条进入该参数的排他规则，保留 AUTO／影片、拍摄编码及 AF-ON 等正常限制。
- [RAW 分组检查](../../dev/pixelshift/raw_group.py)：读取 Sony `PixelShiftInfo`（`0x202f`），检查四张不同源文件、序号及曝光记录，拒绝普通连拍、混合分组和已合成文件。元数据通过不等于证明物理位移或合成兼容。
- [RAW 位移量测](../../dev/pixelshift/displacement.py)：分别比较两个绿色 Bayer 子阵列，量测小数像素平移，检查是否形成一像素方形。独立合成场景通过，不位移、间距错误和坏帧案例被拒绝。已核对真实 C2 普通 RAW 的解码，尚无真实像素位移序列。相机／场景运动也能产生类似影像证据，因此它不能认证马达位置或稳定完成。

序列虚函数 `run()`：C2 为 `0x348bcf0`，A7CR 为 `0x348c1b8`。C2 的 `0x34d1508` 调用封包构造 `0x353a260`；A7CR 的 `0x34d19f0` 调用 `0x353a748`。这些是研究地址，不是刷写位置。该通用命令也用于其他拍摄流程，不能依据这份检查直接向相机发送。

以 A7CR 为主线的 CP 追踪，现已连接模式分派、配置快照和逐张序列选择。A7CR 的 `0x4036` 拍摄请求发往 `0x90040193`，与 `0x40ee` 参数的目的地 `0x90030001` 不同。原生帧构造器会在 TRINITY 各帧间保留同一个分组对象，最后由 `TrinityShotEnd` 重置序号并释放对象。这些是软件生命周期事实，不代表传感器位移或归位。此前查看的 `+0xb8` 到 `+0x1a0` 复制是配置序列化辅助函数，不是 TRINITY 模式的主要来源；不同结构的偏移相同不能证明语义相同。

像素位移的开始拍摄辅助函数会先执行 `0x4040` 状态检查。CP 在请求遮罩与有效状态位没有交集时回覆 `0xf000`，否则回覆 `0xf001`；AP 随后选择发出 `REQUEST_CAPTURE` 或 `CAPTURE_NG`。这定位了查询与事件边界；前面的 CP 触发路径与该事件接收者如何衔接实际曝光仍待追踪，不能把该回覆当作曝光或马达到位确认。

三条原生触发分支各有用途。已检查的 `0x4036` 构造器使用触发值 20，可请求 AE、AF 和 AWB 处理。`0x300e` 转成内部消息 `0x102`，进入 AF 准备；`0x302e` 转成 `0x8307`，已检查的分支只设置 AWBL 旗标，二者都不是捕获开始处理器。另一种 `0x300c` 封包先产生 `0x8202`、再产生 `0x100`，后者才进入会调用配置快照包装层的原生处理器。其发送器前面还有独立的 14 槽捕获注册表及状态／AF 条件。现已重放原始 `0x4038` 的 AP 封包构造，并定位 CP 接收函数，但从 AP 模型事件到物理曝光的完整衔接仍未验证。不能把锁定消息当作位移命令。

串行追踪现已定位元数据路径之外的组合标志／序号字段。`0x6e` 位于 100 字节格式以外，因此即使算出了该字节，扩展区被禁用或发送长度未覆盖它时也不足以传出。这两个条件均用合成输入覆盖；内部接口模式数字不是 Sony 机型编号，也不能证明两台相机实际运行时的协议配置。已静态定位下游 SIO 服务注册及分派函数，但物理接收端如何解释、位移轨迹、稳定等待及归位仍须核对。

官方默认参数实际选择另一条 TC 路径，帧序号会保留在双缓冲的控制快照中；已定位使用该快照的函数，但物理含义仍不明确。另已找到 Darwin 的 34 字节拍摄设置消息及解析函数。重放前段之后的字段进入计时／控制状态，尚未证明是 X/Y 位移坐标。仅封包长度相同，不能连接 CP 发送端与接收端，也不能证明像素位移。

已检查的替代传输分为 type 7 第一阶段和 type 8 第二阶段，均为 40 字节。两份 CP 回覆快照是同一两阶段路径上的不同缓冲区，第一阶段解码器不是旧的 100／128 字节 TC 格式。Bonobo 主镜像代码与两包校验及第二包的模式／向量／TRINITY 字段匹配；实际接线和板级初始化仍未验证。

明确送入下一帧 OFF 的实验，测试的是关闭功能，不是每组正常结束。合成开启状态保留向量，不能据此认定 A7CR 有问题，或要求每组自动关闭功能。原生分组结束路径会重置计数并释放带引用计数的分组对象；仍需一起追踪该释放／回调、正常任务更新及实际定位。

## 虚拟机观察

基于 [a7c2-re](https://github.com/chocotan/a7c2-re) 的实验运行原厂 AP，底层虚拟服务仍有限。原生菜单能显示“关／四张”，选择四张时被 Intelligent Auto 限制挡下，模式与虚拟 Backup 仍为 OFF。提前强制进菜单的配置缺少 `0x4bd` 序列，后来在 `sequence_still_record::suspend(NULL)` 异常；另一次正常启动则确实创建了 `0x4bd`，已沿缓存指针读取元数据核对编号和原生虚表，而不是只看指针非零。此时界面仍黑，MENU 输入没有推进画面。因此，提前进菜单配置的失败不能证明 C2 缺少实现，也不能解释先前的真机故障。完整启动、P/M 输入、选择四张、保存开启后入口隐藏的恢复以及拍摄仍未验证，现有模型不包含传感器／防抖行为。

另一轮虚拟机 RAM 开启／还原循环已确认八处字段回到原值，模式和虚拟 Backup 全程 OFF。只移除／补回四个“参数未定义”计数，保留 AUTO 禁止计数。这验证的是 RAM 逆操作，不代表保存开启后的恢复、闪存持久化或实机还原。

## 离线复现

使用 Python 3.10+，安装[研究依赖](../../dev/pixelshift/requirements.txt)：

```text
python -m pip install -r dev/pixelshift/requirements.txt
python dev/pixelshift/audit.py --c2 private/c2/components --reference private/a7cr/components --output private/audit.private.json
python dev/pixelshift/native_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/replay.private.json
python dev/pixelshift/trinity_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/trinity.private.json
python dev/pixelshift/cp_dispatch_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-dispatch.private.json
python dev/pixelshift/cp_config_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-config.private.json
python dev/pixelshift/cp_mode_source_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-mode-source.private.json
python dev/pixelshift/cp_frame_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-frame.private.json
python dev/pixelshift/cp_serial_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-serial.private.json
python dev/pixelshift/cp_defaults_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-defaults.private.json
python dev/pixelshift/cp_alternate_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-alternate.private.json
python dev/pixelshift/cp_vector_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-vector.private.json
python dev/pixelshift/cp_control_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-control.private.json
python dev/pixelshift/cp_alternate_wire_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-alternate-wire.private.json
python dev/pixelshift/cp_feedback_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-feedback.private.json
python dev/pixelshift/darwin_capture_replay.py --c2 private/c2/components/darwin_core.bin --reference private/a7cr/components/darwin_core.bin --output private/darwin-capture.private.json
python dev/pixelshift/cp_sequence_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-sequence.private.json
python dev/pixelshift/cp_stage_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-stage.private.json
python dev/pixelshift/cp_caif_gpio_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/caif-gpio.private.json
python dev/pixelshift/cp_shadow_load_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/shadow-read.private.json
python dev/pixelshift/cp_grid_source_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/grid-source.private.json
python dev/pixelshift/capture_gate_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capture-gate.private.json
python dev/pixelshift/cp_trigger_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-trigger.private.json
python dev/pixelshift/lifecycle_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/lifecycle.private.json
python dev/pixelshift/cp_group_end_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/group-end.private.json
python dev/pixelshift/cp_group_end_replay.py --c2 private/c2/components --reference private/a7cr/components --full-pool --output private/group-full-pool.private.json
python dev/pixelshift/cp_group_end_replay.py --c2 private/c2/components --reference private/a7cr/components --native-completion --output private/group-completion.private.json
python dev/pixelshift/cp_group_end_replay.py --c2 private/c2/components --reference private/a7cr/components --native-queue --output private/group-queue.private.json
python dev/pixelshift/cp_native_lock_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/native-locks.private.json
python dev/pixelshift/cp_pool_recycle_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/pool-recycle.private.json
python dev/pixelshift/cp_native_mutex_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/native-mutex.private.json
python dev/pixelshift/cp_pool_return_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/pool-return.private.json
python dev/pixelshift/cp_completion_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/completion.private.json
python dev/pixelshift/cp_actor_queue_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/actor-queue.private.json
python dev/pixelshift/cp_actor_delivery_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/actor-delivery.private.json
python dev/pixelshift/cp_queued_end_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/queued-end.private.json
python dev/pixelshift/cp_queued_end_replay.py --c2 private/c2/components --reference private/a7cr/components --consume-completion --output private/queued-consumer.private.json
python dev/pixelshift/cp_queued_end_replay.py --c2 private/c2/components --reference private/a7cr/components --ap-dispatch --consume-completion --output private/ap-clear-consumer.private.json
python dev/pixelshift/cp_completion_consumer_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/completion-consumer.private.json
python dev/pixelshift/cp_poweroff_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/poweroff.private.json
python dev/pixelshift/cp_poweroff_allocate_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/poweroff-allocation.private.json
python dev/pixelshift/cp_poweroff_request_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/local-poweroff-query.private.json
python dev/pixelshift/cp_metadata_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/metadata.private.json
python dev/pixelshift/cp_capture_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-capture.private.json
python dev/pixelshift/cp_timing_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-timing.private.json
python dev/pixelshift/cp_steady_event_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-steady-event.private.json
python dev/pixelshift/capability_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capability.private.json
python dev/pixelshift/option_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/options.private.json
python dev/pixelshift/eligibility_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/eligibility.private.json
python dev/pixelshift/raw_group.py source.ARW
python dev/pixelshift/raw_group.py 1.ARW 2.ARW 3.ARW 4.ARW --validate-four
python dev/pixelshift/displacement.py 1.ARW 2.ARW 3.ARW 4.ARW --output private/displacement.private.json
python -m unittest discover -s dev/pixelshift/tests -v
```

macOS 改用 `python3`，尚未在 Mac 执行验证。未提供私人固件时，七十三项原始固件测试跳过。要运行这些测试，将环境变量 `A7C2_PIXELSHIFT_FIRMWARE_ROOT` 指向含 `a7c2-2.01/components` 和 `a7cr-support/components` 的私人目录。默认参数／替代分支／向量／完整控制／封包／反馈／CAIF 重放还需要将各机型官方的 `CX*00_ALLLANG.bin`、`CX*01_ALLLANG.bin` 放在对应 components 目录；Darwin 测试需要将私人提取的 `0640_darwin/darwin_core.bin` 放在那里。八十五项测试方法涵盖 2621 组配对原生指令案例、26 组参数资格案例、合成元数据异常及位移量测。已有一张真实 C2 普通 RAW 被正确识别为没有像素位移分组。位移量测使用 `rawpy` 保留原 Bayer 采样，四张源 RAW 必须先通过元数据检查。

可选控制器实验需要 Ghidra 11.4.2 和 [H8/300H 语言模块](https://github.com/carllom/sleigh-h8/tree/6eb7c6f8f523ab23ff1aa8076ed5f9d0ac1576cc)。将其 `data`、`Module.manifest` 安装为本地 Ghidra 处理器模块，把[已测试的指令扩展](../../dev/pixelshift/bonobo_h8_extensions.sinc)复制到语言目录，在 `h8300h.slaspec` 末尾加入 `@include "bonobo_h8_extensions.sinc"`，并用 Ghidra 的 SLEIGH 编译器编译。这是有限范围的研究解码器，不是完整 H8/SX 支持。

从官方 `nflasha3` 镜像私下提取 `bonobo.bin`。[镜像提取器](../../dev/pixelshift/bonobo_image.py)移除 0x70 字节容器头，选择第一份独立向量表镜像；整份容器直接按零地址导入会得到错误调用地址。生成的二进制和报告均保留在私人目录：

```text
python dev/pixelshift/cp_phase_pair_replay.py --c2 private/c2/components --reference private/a7cr/components --full-control --output private/cp-pairs.private.json --h8-input private/cp-pairs.private.tsv
python dev/pixelshift/cp_parameter_wire_replay.py --components private/c2/components --output private/parameters.private.json --h8-input private/parameters.private.tsv
python dev/pixelshift/bonobo_image.py private/bonobo.bin --output private/bonobo-primary.bin
analyzeHeadless private h8-research -import private/bonobo-primary.bin -loader BinaryLoader -loader-baseAddr 0 -processor H8:BE:32:H8300 -cspec default -scriptPath dev/pixelshift -postScript BonoboBridgeReplay.java private/cp-pairs.private.tsv private/h8-replay.private.json private/parameters.private.tsv -noanalysis
python dev/pixelshift/cp_controller_reply_replay.py --c2 private/c2/components --reference private/a7cr/components --h8-report private/h8-replay.private.json --output private/controller-reply.private.json
```

H8 重放现已执行原始 BSS 清零片段取得默认覆盖／参考字段，不再直接赋值模式覆盖字段；后续板级配置尚未执行。独立的参数偏置和外设读取值仍为合成输入。新增栈指令形式依照 [GNU H8 模拟器语义](https://github.com/RTEMS/sourceware-mirror-binutils-gdb/blob/master/sim/h8300/compile.c)，回覆函数读取仿真寄存器、编码高半字并自行计算校验。两个 SIO 帧头字节为测试输入。

脚本可选第三个参数额外运行四组参数传输测试（两种输入、两个接收缓冲区），与 16 组命令／回覆测试分开。在参数测试中，偏置经原生 CP／H8 封包代码传入，其余参数字节从合成零 RAM 开始。字节移位标志及多寄存器栈顺序依 GNU 语义检查。这些有限桥接仍由测试依次调用，没有完成整个启动或自动调度的四次曝光。出厂默认值为零，不能据此推断实机调整／标定来源。

若要由原生运算产生尺度，再生成封包，而不是直接给定敏感度字节：

```sh
python dev/pixelshift/cp_scale_calculation_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/calculated-pairs.private.json --h8-input private/calculated-pairs.private.tsv
python dev/pixelshift/cp_scale_acquisition_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/acquired-scales.private.json
```

将 `private/calculated-pairs.private.tsv` 用作 `BonoboBridgeReplay.java` 的第一个参数，并选一个新的输出路径。40 对封包产生 80 组接收缓冲区／命令案例及 160 次错误校验检查。外设回传值仍为独立合成输入。原生运算可能将 255.5 舍入到 256，存为字节零却未设置范围错误；测试保留此行为，不把“未报错”当成物理标定有效。

单独重放输入发布与平均运算（此实验不生成下游向量封包）：

```sh
python dev/pixelshift/cp_input_source_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/input-source.private.json
python dev/pixelshift/cp_context_source_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/context-source.private.json
python dev/pixelshift/cp_device_binding_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/device-binding.private.json
python dev/pixelshift/cp_device_acquire_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/device-acquire.private.json
python dev/pixelshift/cp_capture_gate_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capture-gate.private.json
python dev/pixelshift/cp_capture_context_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capture-context.private.json
python dev/pixelshift/cp_pipeline_source_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/pipeline-source.private.json
python dev/pixelshift/cp_capture_request_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capture-request.private.json
python dev/pixelshift/cp_startup_config_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/startup-config.private.json
python dev/pixelshift/cp_startup_binding_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/startup-binding.private.json
python dev/pixelshift/cp_startup_binding_replay.py --c2 private/c2/components --reference private/a7cr/components --continue-dma --output private/startup-dma.private.json
python dev/pixelshift/cp_sample_stage_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/sampling-stage.private.json
```

`analyzeHeadless` 位于 Ghidra 的 `support` 目录，Windows 使用 `analyzeHeadless.bat`。桥接从硬件接收之后开始，覆盖默认值来自原生清零，接收状态、参数偏置及外设值为合成输入，停在后续控制器处理之前。它没有启动整个控制器，也没有用成功返回值代替硬件响应。

## 尚需实现

保持已撤回的实机候选关闭，继续核对虚拟机正常启动／菜单流程和单张配置、CP／防抖定位入口，确认定位单位、稳定完成条件、曝光同步及完成／取消后的归位。再次实机测试之前，需要可独立审查的候选、断电后仍可用的 OFF 入口及精确还原方案。之后仍须验证实际位移 RAW、分组／校准记录和兼容合成。有五轴防抖或共用名称，不代表已具备定位接口，目前没有可刷写候选。

不能只打开菜单、复制 A7CR 机身校准、伪造 RAW 分组／机型，或把普通连拍称为像素位移。完整固件、原始照片和生成报告留在私人目录。main 和 Releases 保持不变。

原生参考：[A7CR 像素位移说明](https://helpguide.sony.net/ilc/2370/v1/en/contents/0414M_pixel_shift_shooting.html)、[Sony 合成流程](https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/1_2_about_psm.php)。
