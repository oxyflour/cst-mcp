# 娉ㄥ叆 CST 杩涚▼璋冪敤 ACIS锛氬疄娴嬬粨璁轰笌鏂藉伐璺嚎

> **勘误（重要）**：本文是调查过程的按时间记录，中间结论已被后面的实测推翻。读之前先看这两条：
> - §12「ACIS 读 SAT 不通」已被 **§13 推翻**：根因是 DLL 用了静态 CRT（`/MT`），改 `/MD` 后
>   `api_restore_entity_list` 正常。
> - §14「推拉面全部空转」已被 **§15 推翻**：`api_tweak_faces` 是"替换曲面"不是"移动面"，
>   移动要用 `api_move_faces` + 真正的 `SPAtransf`。
> 结论以 §13 / §15 为准，前面的失败记录只作证据。

鍓嶆彁锛氱洰鏍囨槸**鍦?CST 杩涚▼鍐?*鐢?CST 宸茬粡鍒濆鍖栥€佸凡缁忔巿鏉冪殑 ACIS 鍐呮牳寤?鏀?BRep锛岃€屼笉鏄蛋 VBA銆?鏈枃鐨勬瘡鏉＄鍙枫€佺増鏈€佸鍏ュ叧绯婚兘鏄湪杩欏彴鏈哄櫒涓婁粠 PE 閲岃鍑烘潵鐨勶紝涓嶆槸鎺ㄦ祴銆?
---

## 1. 鍏堢籂姝ｄ竴涓叧閿偣锛欰CIS 涓嶅湪 DE 閲?
闈欐€佸鍏ラ摼锛坄out/*.exports.txt` + 瀵煎叆琛ㄦ壂鎻忥級锛?
```
modeler_AMD64.exe  鈹€鈹€imports鈹€鈹€鈻? AcisInterface_AMD64.dll  鈹€鈹€imports鈹€鈹€鈻? SpaACIS.dll
                                  AcisTools_AMD64.dll     鈹€鈹€imports鈹€鈹€鈻? SpaACIS.dll
```

- `CST DESIGN ENVIRONMENT_AMD64.exe` **涓嶅鍏?* ACIS 鐩稿叧妯″潡銆?- `modeler_AMD64.exe`锛?14 MB锛?D 寤烘ā閭ｄ釜鐙珛杩涚▼锛夊鍏?`AcisInterface_AMD64.dll`锛屽悗鑰呭鍏?`SpaACIS.dll`銆?- 鍙﹀ 26 涓ā鍧楃洿鎺ュ鍏?`SpaACIS.dll`锛歚TetMesh_AMD64.exe`銆乣MeshRefinement_AMD64.dll`銆乣SatMifInterface_AMD64.dll`銆乣Solver_HF_*`銆乣eda_interface_AMD64.dll` 绛夈€?
**缁撹锛氳娉ㄥ叆鐨勬槸 `modeler_AMD64.exe`锛屾敞鍏?DE 鎷夸笉鍒?ACIS銆?*
锛堟眰瑙?缃戞牸杩涚▼涔熷悇鏈変竴浠?ACIS锛岃嫢瑕佸湪姹傝В渚у姩鎵嬪啀鍗曠嫭娉ㄥ叆銆傦級

## 2. 鍐呮牳鐗堟湰涓庡鍑洪潰

| 椤?| 鍊?|
|---|---|
| 鏂囦欢 | `ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll`锛?0.3 MB锛寈64锛寁141 (VC2017) |
| 鐗堟湰璧勬簮 | `20211.0.1.21112` = **ACIS 2021 1.0**锛坄SPAAcisPack`锛?|
| 鍛藉悕瀵煎嚭 | **50 832** 涓紙`out/SpaACIS.full.exports.txt`锛?|
| 鍏朵腑 `?api_*` | **1 307** 涓?鈥斺€?鏁村 ACIS C API 閮藉湪 |
| 瑁?`api_*`锛圕 鍚嶏級 | **0** 涓紙`GetProcAddress("api_start_modeller")` 瀹炴祴杩斿洖 NULL锛?|
| 瑁?C 瀵煎嚭 | 鍙湁 63 涓繍琛屾椂杈呭姪锛歚acis_malloc`銆乣sys_error`銆乣signal_interrupt` 绛?|

涔熷氨鏄锛?*C API 鍏ㄥ湪锛屼絾鍏ㄩ儴鏄?C++ 淇グ鍚嶏紝涓旇繑鍥炲€兼槸 `outcome` 绫诲€笺€?*

鐪熷疄鐨勭鍙烽暱杩欐牱锛堝師鏍锋憳褰曪級锛?
```
?api_start_modeller@@YA?AVoutcome@@H@Z
?api_solid_block@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVBODY@@PEAVAcisOptions@@@Z
?api_body@@YA?AVoutcome@@AEAPEAVBODY@@PEAVAcisOptions@@@Z
?api_body_mass_props@@YA?AVoutcome@@PEAVBODY@@AEAVmass_props@@PEAVmass_props_options@@PEAVAcisOptions@@@Z
```

`?api_solid_block@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVBODY@@PEAVAcisOptions@@@Z` 瑙ｇ爜灏辨槸锛?
```cpp
outcome api_solid_block(const SPAposition&, const SPAposition&, BODY*&, AcisOptions*);
```

## 3. 杩欎欢浜嬬殑纭棬妲涳細涓嶆槸娉ㄥ叆锛屾槸 ABI

娉ㄥ叆鏈韩鏄?20 琛屼唬鐮併€傜湡姝ｅ崱浣忕殑鏄?*鎬庝箞姝ｇ‘璋冪敤杩欎簺绗﹀彿**锛?
1. 杩斿洖鍊?`outcome` 鏄被锛堟寜 MSVC x64 瑙勫垯锛岄潪骞冲嚒绫绘寜闅愯棌鎸囬拡杩斿洖锛夈€備綘涓嶇煡閬撳畠鐨?8 瀛楄妭甯冨眬锛屽氨鍙兘鎶婅皟鐢ㄧ害瀹氬啓閿欍€佹爤鐩存帴鐑傛帀銆?2. `SPAposition`銆乣ENTITY`銆乣BODY`銆乣AcisOptions` 閮芥槸绫?缁撴瀯锛沗BODY*&` 杩欑被寮曠敤鍙傛暟瑕佷紶鎸囬拡鐨勫湴鍧€銆?3. 鍙傛暟閲屾湁榛樿鍊硷紙`AcisOptions* = nullptr`锛夛紝淇グ鍚嶅彧鍙嶆槧瀹為檯绛惧悕锛屼笉鍙嶆槧榛樿鍊尖€斺€旀墍浠ユ瘡涓嚱鏁伴兘寰楃収淇グ鍚嶉噸寤恒€?
### 3.1 `outcome` 鐨?ABI 宸蹭粠 CST 鑷繁鐨勬満鍣ㄧ爜閲屽弽鎺ㄥ嚭鏉?
`AcisTools_AMD64.dll` 閲屽 `?api_restore_entity_list@@...` 鐨勮皟鐢ㄧ偣锛堝弽姹囩紪鍘熸枃锛夛細

```
lea   rcx, [rbp+0x1f]        ; 鈫?闅愯棌杩斿洖缂撳啿鍖烘寚閽堬紙RCX锛?mov   rdx, rdi               ;   FILE*
mov   r8d, r14d              ;   int
lea   r9,  [rbp+0x5f]        ;   ENTITY_LIST&
mov   [rsp+0x20], r15        ;   AcisOptions*锛堟爤涓婄 5 涓弬鏁帮級
call  qword ptr [rip+0x9dc97] ; 鈫?api_restore_entity_list
```

鍙傛暟椤哄簭涓庝慨楗板悕 `(FILE*, int, ENTITY_LIST&, AcisOptions*)` 瀹屽叏瀵逛笂锛屼笖**杩斿洖鍊艰蛋 RCX 闅愯棌鎸囬拡**銆?缁撹锛歚outcome` 鏄潪骞冲嚒绫伙紝鎸夊€艰繑鍥炴椂鐢辫皟鐢ㄦ柟鎻愪緵缂撳啿鍖恒€?*鍙鎴戜滑鐨勫０鏄庢槸涓€涓?>16 瀛楄妭銆?6 瀛楄妭瀵归綈鐨勭粨鏋勪綋锛孧SVC 鐢熸垚鐨勮皟鐢ㄥ簭鍒楀氨鍜?CST 涓€鑷淬€?*

浜庢槸涓嶉渶瑕佸ご鏂囦欢锛?
```cpp
struct outcome_slot { alignas(16) unsigned char storage[256]; };

using pfn_solid_block = outcome_slot (*)(const SPAposition*, const SPAposition*, BODY**, AcisOptions*);
auto f = (pfn_solid_block)GetProcAddress(hSpaACIS,
            "?api_solid_block@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVBODY@@PEAVAcisOptions@@@Z");

SPAposition lo(0,0,0), hi(10,10,10);
outcome_slot oc;                 // 涓嶅垵濮嬪寲锛岀敱琚皟鏂瑰湪鑷繁鐨勮繑鍥炴Ы閲屾瀯閫?BODY* body = nullptr;
f(&lo, &hi, &body, nullptr);     // 鍙傛暟涓嶈冻 9 涓椂 AcisOptions* 浼?nullptr 鍗冲彲

auto ok    = (int(*)(const void*))GetProcAddress(hSpaACIS, "?ok@outcome@@QEBAHXZ");
auto errno_= (int(*)(const void*))GetProcAddress(hSpaACIS, "?error_number@outcome@@QEBAHXZ");
auto dtor  = (void(*)(void*))    GetProcAddress(hSpaACIS, "??1outcome@@QEAA@XZ");
int good = ok(&oc), err = errno_(&oc);
dtor(&oc);                       // 蹇呴』璋冿紝outcome 閲屽彲鑳芥湁 std::string
```

`outcome` 鐨勬垚鍛樺竷灞€瀹屽叏涓嶇敤鐭ラ亾鈥斺€擿ok`銆乣error_number`銆乣~outcome` 閮芥湁瀵煎嚭绗﹀彿锛岀洿鎺ユ寜鎴愬憳鍑芥暟璋冿紙this 鍦?RCX锛夈€?
### 3.2 杩欎釜濂楄矾鑳借鐩栧灏?
`outcome` 杩欎竴鍏抽€氫簡浠ュ悗锛屽墿涓嬬殑 1307 涓?`api_*` 閮芥槸"鐓т慨楗板悕鍐欎竴涓嚱鏁版寚閽堢被鍨?锛?
- `SPAposition` = `double x,y,z`锛屾寜寮曠敤浼狅紙`AEBVSPAposition`锛夊氨鏄紶鎸囬拡锛?- `ENTITY*` / `BODY*` / `AcisOptions*` 涓€寰嬪綋涓嶉€忔槑鎸囬拡锛宍AcisOptions*` 浼?`nullptr` 璧伴粯璁ゅ€硷紱
- 寮曠敤鍑哄弬 `AEAPEAVBODY` = `BODY**`锛?- 鍙湁鍑虹幇**鎸夊€间紶缁撴瀯浣?*锛堝 `SPAvector`銆乣mass_props`锛夋椂鎵嶉渶瑕佺煡閬撳竷灞€鈥斺€擿mass_props` 杩欑被鍙互鍏堢敤瓒呭ぇ buffer 璇曪紝鎴栧共鑴嗚蛋 `api_body_mass_pr`锛堝叏鏍囬噺鍑哄弬锛夈€?
鐪熸鐨勯闄╀笉鍐嶆槸 ABI锛岃€屾槸**璇箟**锛氭瘡涓?API 鐨勫墠缃潯浠躲€侀渶瑕佸摢涓?`api_initialize_xxx` 宸叉墽琛屻€佽繑鍥炵殑 `ENTITY*` 褰掕皝绠°€傝繖浜涘彧鑳戒竴涓嚱鏁颁竴涓嚱鏁拌瘯銆?
鏈?ACIS 2021 1.0 澶存枃浠跺綋鐒舵洿鐪佷簨锛坄.def` 鈫?瀵煎叆搴?鈫?姝ｅ父 include锛夛紝浣嗘病鏈変篃鑳借蛋锛屽彧鏄參銆?
## 4. 绾跨▼涓?entity manager锛氭渶瀹规槗缈昏溅鐨勫湴鏂?
ACIS 2021 鏄?**part/绾跨▼鐩稿叧**鐨?entity manager锛坄acis_pm_entity_mgr`銆乣PART::get_entity_manager` 杩欎簺绗﹀彿閮藉湪锛夈€?
- 瀵煎嚭琛ㄩ噷**娌℃湁**鍏ㄥ眬 `get_entity_manager()`锛屼篃娌℃湁 `api_get_entity_manager`銆備篃灏辨槸璇翠綘鎷夸笉鍒?EM 鎸囬拡鈥斺€斾絾 **寤哄嚑浣曞苟涓嶉渶瑕佸畠**锛歚api_solid_block` 浼氶殣寮忎娇鐢ㄨ皟鐢ㄧ嚎绋嬪綋鍓嶇殑 part銆?- 鍚庢灉锛氬鏋滀綘鍦ㄨ嚜宸?`CreateThread` 鍑烘潵鐨勭嚎绋嬮噷璋冪敤锛宍BODY*` 浼氳寤哄埌**鍙︿竴涓?part** 閲岋紝CST 鐨勬ā鍨嬫爲鐪嬩笉鍒板畠锛屽悗缁?`api_*` 涔熷彲鑳藉洜涓轰笂涓嬫枃涓嶄竴鑷磋繑鍥?`outcome` 閿欒鎴栫洿鎺ュ穿銆?- **鎵€浠ユ墍鏈?ACIS 璋冪敤蹇呴』鍥炲埌 modeler 鐨勪富绾跨▼鎵ц**锛堟秷鎭车 + 闅愯棌绐楀彛锛屾垨 `WH_CALLWNDPROC` 鎷夸竴娆℃墽琛屾潈鍚庤嚜寤?`WM_APP` 绐楀彛锛夈€傝繖灏辨槸"娉ㄥ叆 DLL 鍙仛浠ｇ悊"鐨勫叏閮ㄥ師鍥犮€?- **涓嶈璋冪敤 `api_start_modeller`**锛欳ST 宸茬粡鍒濆鍖栬繃銆傞噸澶嶅垵濮嬪寲浼氶噸缃?鍐茬獊銆備綘鍙渶瑕佽皟浣犵湡姝ｈ鐢ㄧ殑閭ｅ嚑涓嚱鏁般€?
## 5. 寤哄嚭鏉ョ殑 BODY 鎬庝箞浜ゅ洖 CST

涓夋潯璺紝鎸夐闄╀粠浣庡埌楂橈細

| 璺嚎 | 鍋氭硶 | 璇勪环 |
|---|---|---|
| SAT 涓浆 | 杩涚▼鍐?`api_save_entity_list_to_file` 鍐?`.sat` 鈫?CST VBA 瀵煎叆 | **鏈€绋?*锛岃法鐗堟湰涓嶇牬锛涗唬浠蜂竴娆℃枃浠?I/O |
| CST 鑷湁鎺ュ彛 | `SatMifInterface::add_entity(ENTITY*, name, ...)`锛?7 涓鍑猴紝宸茬‘璁ゅ瓨鍦級 | 鐢ㄤ簬姹傝В鍣ㄤ氦鎺ワ紝涓嶆槸寤烘ā鏍戯紝闇€鍐嶉獙璇?|
| 閫嗗悜寤烘ā鏍?| `ModellingIO_AMD64.dll` / `Geom_AMD64.dll` 閲岀殑 shape 瀹瑰櫒 | 绗﹀彿鏈€澶氥€佹渶涓嶇ǔ瀹?|

娉ㄦ剰锛歚SatMifInterface` 鐨?`add_entity(ENTITY*, ...)` 璇存槑 CST 鍐呴儴灏辨槸浼犺８ `ENTITY*`鈥斺€斾綘鐨?`BODY*` 鍜屽畠鐨勭被鍨嬬郴缁熸槸鍚屼竴濂楋紝绫诲瀷涓婃病鏈夐殰纰嶏紝闅滅鍙湪"鍝釜瀹瑰櫒鎺?銆?
## 6. 宸茬粡鍐欏ソ鐨勮浇鑽凤紙瀹屾暣闂幆锛?
`native/` 涓嬪洓涓枃浠讹紝绗竴娆″疄娴嬬敤锛?
| 鏂囦欢 | 浣滅敤 |
|---|---|
| `acis_shim.h` | 涓嶄緷璧?ACIS 澶存枃浠剁殑鏈€灏忓０鏄庯細`SPAposition`銆乣outcome_slot`銆乣ok`/`error_number`/`~outcome` 涓庡父鐢?`?api_*` 鐨勪慨楗板悕甯搁噺 |
| `acis_direct.h` | 鐩存帴寤烘ā瀛愰泦鐨勫嚱鏁版寚閽堢被鍨?+ 淇グ鍚嶅父閲忥紙鍋忕疆銆佸竷灏斻€佷慨澶嶃€佸€掕銆佹煡璇級 |
| `cst_acis_probe.cpp` | 娉ㄥ叆鍚庤嚜鍔ㄨ窇闂幆锛歚api_initialize_offsetting` 鈫?`api_solid_block` 閫?10鲁 鏂瑰潡 鈫?`api_get_faces` 鏋氫妇闈紙`PAT_NEXT_TYPE` 璇?0..3锛夆啋 `api_entity_extrema` 瀹氫綅 鈫?`api_offset_face` 鍋忕疆 2.0锛屾瘡姝ョ敤 `ok`/`error_number` 鍒ゅ畾 |
| `inject.ps1` | 绾?PowerShell 娉ㄥ叆鍣紙`OpenProcess` + `VirtualAllocEx` + `CreateRemoteThread(LoadLibraryW)`锛夛紝涓嶉渶瑕佺紪璇戝櫒 |

```powershell
# 1. 瑁?VS Build Tools 鐨?"x64 Native Tools Command Prompt"锛岀劧鍚?cd native; .\build.bat

# 2. CST 閲屾墦寮€涓€涓?3D 椤圭洰锛坢odeler_AMD64.exe 鎵嶄細瀛樺湪锛?.\inject.ps1 -Dll .\cst_acis_probe.dll

# 3. 鐪嬬粨鏋?notepad "$env:TEMP\cst_acis_probe.<pid>.log"
```

`ENTITY_LIST` 涔熸槸闈犲畠鑷繁鐨勫鍑烘垚鍛橀┍鍔ㄧ殑锛坄??0` 鏋勯€犮€乣?count@` 鍙栨暟閲忋€乣??A` 鍙栧厓绱犮€乣??1` 鏋愭瀯锛夛紝鎵€浠ヨ繛瀹冪殑绫诲竷灞€閮戒笉鐢ㄧ煡閬撱€?
鏃ュ織鎸夐『搴忕粰鍑猴細`api_initialize_offsetting` 鈫?`api_solid_block` 鈫?`api_get_faces(pat=0..3)` 鍚勮嚜杩斿洖鐨勯潰鏁?鈫?`api_entity_extrema` 鍧愭爣 鈫?`api_offset_face` 鐨?`ok` 涓庢柊浣撴寚閽堛€傛渶鍚庝竴琛屾墦鍗?`SUCCESS` 灏辫鏄庢敞鍏ャ€佺嚎绋嬨€丄BI銆佺粍浠跺垵濮嬪寲銆佸疄浣撳彞鏌勮繖鏉￠摼鍏ㄩ儴鎴愮珛銆?
> **宸茬鍒扮楠岃瘉**锛?026-10-27锛屾湰鏈猴級锛歁SVC 14.44 缂栬瘧閫氳繃锛屾敞鍏?`modeler_AMD64.exe` 杩炶窇涓夋鍧囨垚鍔燂紝瀹為檯鏃ュ織锛?
```
ui thread id=32260
[work] tid=32260
SpaACIS base=00007FFB68750000
  api_initialize_offsetting    ok=1 errno=0
  api_solid_block              ok=1 errno=0
[work] body=000002A4C542B6C0
[work] api_get_faces(pat=0) ok=1 errno=0 count=6
[work] first face=000002A4C5FFCA38
  api_entity_extrema           ok=1 errno=0
[work] extremum at (0.000, 0.000, 0.000)
  api_offset_face              ok=1 errno=0
[work] offset body=000002A4C5FFCB18
  new body faces              ok=1 errno=0 count=1
[work] SUCCESS: inject + thread + ABI + component init + entity handle all work
```

鏂瑰潡 6 涓潰銆佸亸缃嚭鏉ョ殑鏂颁綋 1 涓潰锛屼笌 ACIS 璇箟涓€鑷达紝璇佹槑 `outcome` 闅愯棌鎸囬拡 ABI銆乣SPAposition` 甯冨眬銆乣BODY*&` 鍑哄弬銆佺嚎绋嬪綊灞炲叏閮ㄦ纭紝涓嶅彧鏄?杩斿洖 ok"銆?
缂栬瘧韪╁埌鐨勪袱涓潙锛堝凡淇級锛氶摼鎺ヨ鍔?`user32.lib`锛涙棩蹇楁枃浠惰鐢?`_fsopen(..., _SH_DENYNO)`锛屽惁鍒欒繘绋嬪唴涓€鐩存寔鏈夊彞鏌勩€佸閮ㄨ涓嶄簡銆?
## 7. 杩樻病瑙ｅ喅鐨勯棶棰?
1. ~~鏈夋病鏈?ACIS 澶存枃浠秪~ 鈫?娌℃湁涔熻兘璧帮紝瑙?搂3.1锛涗唬浠锋槸姣忎釜 API 瑕佹墜鍐欎竴娆″嚱鏁版寚閽堢被鍨嬨€?2. **鍝簺 API**锛氭妸浣犺鐢ㄧ殑鍔熻兘鍒楀嚭鏉ワ紙鍙橀噺鍊掕銆佹娊澹炽€佸亸缃€佸共娑夋鏌ャ€佺簿纭潰鐗囥€佹剤鍚堚€︹€︼級锛屾垜鎸変慨楗板悕浠?`out/SpaACIS.full.exports.txt` 閲屽畾浣嶅苟缁欏嚭鍙紪璇戠殑鍘熷瀷銆?3. **BODY 鎬庝箞鍥?CST**锛氬厛鎸?搂5 鐨?SAT 涓浆鎵撻€氾紝鍐嶈€冭檻鎺?`SatMifInterface`銆?
## 8. 鍚堣

ACIS 鐨勬巿鏉冩槸缁戝湪 CST 鐨?license 涓婄殑锛涘湪 CST 杩涚▼鍐呭鐢ㄥ畠鐨勫唴鏍革紝缁曡繃 Spatial 鐨勭嫭绔嬫巿鏉冿紝`[寰呯‘璁` 閫氬父涓?EULA 鍐茬獊銆傝繖鏉′笉褰卞搷鎶€鏈彲琛屾€э紝浣嗕細褰卞搷浣犺兘涓嶈兘浜や粯缁欏鎴枫€?
---

闄勶細`scripts/pe_exports_full.py` 鍙互閲嶆柊瀵煎嚭浠绘剰 PE 鐨勫畬鏁村鍑鸿〃锛坧efile 鍦ㄨ秴杩?8192 涓悕瀛楁椂浼氭埅鏂紝鍒敤瀹冩暟锛夈€傚畬鏁寸鍙锋竻鍗曞湪 `out/SpaACIS.full.exports.txt`銆?

## 9. SAT 交接的实测结果

进程内调用 ACIS 成功之后，把几何交给 CST 这件事分两段，一段通、一段卡住：

| 环节 | 结果 |
|---|---|
| ACIS 建体 / 枚举面 / 偏置 | ✅ 已验证（§6 日志） |
| `api_save_entity_list(FILE*, ...)` 写 SAT | ❌ 在内部 fail-fast（`ucrtbase.dll` 偏移 `0x11858`，`0xC0000409`）。排除过两种猜测：①不是栈溢出——换成 8 KB 堆缓冲后故障偏移一模一样；②不是参数顺序——CST 自己在 `SatMifInterface` 里的调用序列与我们逐字节一致。剩下就是它不认外部 CRT 打开的 `FILE*` |
| `SatMifInterface::write_sat_file_only(path, scale)` 写 SAT | ✅ 可用。CST 自己的写入器，只接 `std::string` 路径，不跨 CRT 传句柄。产出合法 SAT：方块 2474 字节（`100 87 0 0` 头 + `body` 记录）、片体 700 字节 |
| CST 侧 VBA 导入 | ✅ `With SAT / .Reset / .FileName / .Version "9.0" / .Read / End With`。注意对象是 `SAT`、方法是 `.Read`；`With Import ... .Import` 是无效写法，会静默什么都不做 |

调试导入命令时踩到的坑：CST 的历史列表**一旦某个块执行失败就会静默停摆**，之后 `add_to_history` 全部返回成功但什么也不做，`StoreParameter` 也不再生效。判断"命令有没有生效"必须每次换干净项目。

### 下一步最短路径

在 CST 里手动做一次 `Modeling: Exchange > Import > 3D Files > ACIS SAT/SAB`，然后把 History List 里新生成的那几行 VBA 抄出来——这就是准确命令，比猜快得多。拿到之后把 `scripts/import_sat_test.py` 里的候选换成它即可。

### 关于"先写字符串再写文件"

这个 build **没有** `StringFileInterface`：只有抽象的 `FileInterface` 和 `SummaryFileInterface`，`api_save_entity_list_file()` 收的是 `FileInterface*`。想要内存串，只能自己实现一个 `FileInterface` 子类——vtable 是导出的（`??_7FileInterface@@6B@`），每个槽都能映射到导出的 `write_string`/`write_int`/`write_real`/`write_header` 等成员函数，接口可以重建，但要实现约 40 个虚函数。

而且**没收益**：CST 的导入接口吃的是文件路径（`.FileName "..."`），不是流。SAT 内容就算在内存里，最后仍然要落盘。落盘这条路已经有可用实现（`SatMifInterface::write_sat_file_only`，2474 / 700 字节已验证），所以字符串方案只解决一个已经解决了的问题。

### 完整链路已跑通（2026-10-28）

```
注入 modeler_AMD64.exe
  → api_solid_block 造 10×10×10 方块
  → SatMifInterface::write_sat_file_only 写 .sat（2474 字节）
  → CST VBA: With SAT ... .Read
  → 3D 视图里出现方块
```

截图确认（`%TEMP%\sat_import.png`）：导航树里出现实体、3D 视图显示出 10³ 立方体。

CST 侧的完整命令：

```vb
With SAT
     .Reset
     .FileName "C:\Users\<user>\AppData\Local\Temp\cst_acis_block.sat"
     .Id "1"
     .Version "9.0"
     .ScaleToUnit "0"
     .ImportToActiveCoordinateSystem "True"
     .Curves "True"
     .Read
End With
```

踩过的坑：`With Import ... .Import` 不会报错，但什么也不做；CST 的历史列表一旦某个块执行失败就静默停摆，之后 `add_to_history` 全部返回成功却不再执行，判断命令是否生效必须用干净项目。

片体（`cst_acis_sheet.sat`，单面偏置产物）导入后视图没变化，可能是平面正好落在立方体内部被遮挡，也可能单面体的 SAT 读取需要别的选项——未深究。

## 10. 方案 2（直接用 Spatial InterOp）的实测进度

`InteropConverter_AMD64.exe` 的导入表指向 `SPAIop.dll` / `SPAIInterop.dll` / `SPAIopAcis.dll`，它们位于
`ACIS_interop\NT_VC16_64_DLL\code\bin\`。其中 `SPAIInteropC.dll` 暴露了一套**无头文件可调**的 C 接口：

```
?SPAICSystem_Initialize@@YAHXZ                              int  ()
?SPAICSystem_Shutdown@@YAHXZ
?SPAICConverter_Create@@YAXPEAPEAX@Z                        void (void**)
?SPAICConverter_Convert@@YAJPEAX00@Z                        long (conv, in, out)
?SPAICConverter_RegisterComponent@@YAJPEB_W0H0@Z
?SPAICFile_Create@@YAXPEAPEAXPEBD@Z                         void (void**, const char*)
?SPAICDocument_Create@@YAXPEAPEAXPEBD@Z
?SPAICDocument_SetType@@YAJPEAXPEBD@Z
?SPAICOptions_Create@@YAXPEAPEAX@Z
?SPAICValue_Create@@YAXPEAPEAXPEBD@Z
```

`native/iop_convert.cpp` 是一个独立小程序，已验证到：

```
SPAICSystem_Initialize -> 0
RegisterComponent(STEP/IGES/ACIS/Parasolid) -> 0x0
converter 创建成功
Convert -> 0x02000003（success 严重级），但不产出文件
```

结论：接口能调，但 Convert 缺少"输出格式/选项"配置。`0x02000003` 是 success 级 code 而不是 failure，
说明调用本身被接受了，只是没选对输出类型——要靠 `Options_*` / `Document_SetType` 补，但选项语义无文档。

两个未知数，都只能靠反汇编或 Spatial 文档解决。转去走 CST 驱动（§9）更划算。

## 11. VBA 文档里的 SAT 导出/导入（已核对）

`Online Help\mergedProjects\VBA_3D\common_vbaimpexp\common_vbaie_sat.htm` 给出了完整方法表：

| 方法 | 说明 |
|---|---|
| `.FileName (name)` | 导入/导出的文件名 |
| `.Id (int)` | 同一文件多次导入时区分中间产物 |
| `.Version (double)` | 导入过滤器版本，最新 `9.0` |
| `.ScaleToUnit (bool)` / `.ImportToActiveCoordinateSystem (bool)` | 导入选项 |
| `.ExportFromActiveCoordinateSystem (bool)` | 导出时按激活坐标系变换 |
| `.Curves / .Wires / .SolidWiresAsSolids (bool)` | 曲线/线缆处理 |
| `.Read` | 执行导入 |
| **`.Write (name)`** | 导出指定 shape 或整个 component |
| **`.WriteAll`** | 导出全部 |
| `.WriteSelectedSolids` | 导出选中的实体 |

实测：

```
With STEP ... .Read                                  -> basic-phone.stp 进入 3D 视图
With SAT ... .WriteAll                               -> 80517 字节，头 "3100 0 1 0 ... CST MICROWAVE STUDIO 14 ACIS 31.0.1"
```

即 **CST 模型 → SAT 这条路通了**。

## 12. ACIS 读 SAT 的结论：不通

给代理加了 `restore <path>`（`api_restore_entity_list(FILE*, int, ENTITY_LIST&, AcisOptions*)`）后实测：

```
[pipe] <- ping          -> OK pong
[pipe] <- restore ...   -> （连接断开）
Faulting module: ucrtbase.dll   Exception code: 0xc0000409   Fault offset: 0x11858
```

与 `api_save_entity_list` 完全相同的故障点。**ACIS 的 `FILE*` 入口进出都不接受外部 CRT 打开的流**。

替代入口 `api_restore_entity_list_file(FileInterface*, ...)` 和 `api_save_entity_list_file(...)` 存在，但需要自己实现抽象的
`FileInterface`（vtable 是导出的 `??_7FileInterface@@6B@`，槽位能对应到导出的 `write_string`/`read_int` 等成员）。
`asm_save_file` / `asm_restore_file` 只有默认构造，没有路径构造，帮不上。

## 13. 根因：静态 CRT（/MT）→ 换 /MD 后全部打通

之前 `api_save_entity_list` 和 `api_restore_entity_list` 都在 `ucrtbase.dll` 偏移 `0x11858` fail-fast。
原因不是 `_wfopen` / `_fopen`，是 **CRT 实例不同**：DLL 用 `cl` 默认的静态 CRT（`/MT`），导入表里只有
KERNEL32/USER32，`_fsopen` 造出的 `FILE*` 属于我们私有的文件表，`SpaACIS` 内部走 ucrtbase，拿到就是无效句柄。

加 `/MD` 后导入表变成：

```
KERNEL32, USER32, VCRUNTIME140, api-ms-win-crt-{heap,runtime,stdio,string}-l1-1-0
```

实测：

```
ping                    -> OK pong
restore C:\...\phone.sat -> OK entities=1 body=0x... faces=38
offset 0 2.0            -> OK body=0x... faces=1
save ...                -> OK bytes=1893
SAT.Read                -> 导入成功
```

38 个面就是 `basic-phone.stp` 的主体 B-rep。完整链路：

```
STEP 导入(CST) → SAT 导出(SAT.WriteAll) → ACIS restore → ACIS 编辑 → SAT 写回 → 导入(CST)
```

> **构建必须带 `/MD`**（`native/build.bat` 已固定）。用 `/MT` 会在第一次碰 `FILE*` 时崩掉 modeler，
> 而且崩在 ucrtbase，很容易误判成 API 用法错误。

## 14. 推拉面（push/pull）实测

### ACIS 侧：能调，但不干活

`native/cst_acis_agent*.dll` 里试过 5 种写法，全部返回 `ok=1` 而几何不变（`bbox` 前后完全一致）：

| 调用 | 结果 |
|---|---|
| `api_tweak_faces`（delta 按值） | ok，无变化 |
| `api_tweak_faces`（delta 按引用 + `lop_options`） | ok，无变化 |
| `api_tweak_faces_init`（带 ENTITY_LIST 出参） | ok，`affected=0` |
| `api_move_faces`（单位变换 + from/to） | ok，无变化 |
| 先 `api_initialize_local_ops` / `lopt_ops` 再调 | 初始化 ok=1，操作仍无变化 |

回引规则已确认：`api_get_entity_box` 的 `1` 指向第 2 个参数（`SPAposition&`），所以 `tweak_faces` 里那个 `3` 是
第 4 个参数 `int*`，不是隐藏的 `SPAposition`。签名没错，是**语义**缺东西——这套 lopt API 需要目标 `SURFACE**`
数组或 part 上下文，没有文档重建不出来。

### CST 侧：有现成的，而且更稳

`VBA_3D\common_vbasolido\common_vbasolido_local_modifications_object.htm` 定义了 `LocalModification` 对象：

```
Reset
Name (solidname) / AddName (solidname)
SetConsiderBlends (bool)        ' 相邻圆角先拆、操作后按新位置补回
EnableInvertedFaceRemoval (bool)
OffsetSelectedFaces (amount)    ' 沿面法向推拉，自动调整邻接面保持闭合
MoveSelectedFaces (dx, dy, dz)
RemoveSelectedFaces ()          ' 删面并放大邻接面，补不上就整体不执行
DefineConstraintSelectedFaceRadius / PlaneDistance / PointDistance
```

配 `Pick.PickFaceFromId (shapeName, id)` 选面。第一次试没生效，原因是 shape 名/面 id 是猜的
（`component1:solid1` / id 5），且 CST 历史块一次失败后会静默停摆。

### 关于 "progressive 模式"

ACIS 里没有这个名字的东西。接近的机制有三处：

- 圆角重试：全局 option `bl_retry_allow` / `bl_retry_detect_success`（`option_header` 类型，需要 option 机制设置）
- 局部操作多解：`api_tweak_query_edge_solutions(EDGE*, ENTITY_LIST&, AcisOptions*)` 列候选，
  `api_tweak_pick_edge_solution(EDGE*, int, CURVE*, AcisOptions*)` 选定后重试
- CST `LocalModification` 的容错开关：`SetConsiderBlends`、`EnableInvertedFaceRemoval`，
  以及 `RemoveSelectedFaces` 的"补不上就整体拒绝"

**结论：推拉该走 CST 的 `LocalModification`，不该走 ACIS lopt。**

### 推拉面：可用的写法（已实测）

历史块里可以直接用 `Pick` + `LocalModification`，**不需要注入 ACIS**：

```vb
Pick.PickFaceFromId "component1:solid1", "1"
With LocalModification
     .Reset
     .Name "component1:solid1"
     .EnableInvertedFaceRemoval "True"
     .SetConsiderBlends "False"
     .OffsetSelectedFaces "1.5"      ' 沿法向推拉；或 .MoveSelectedFaces "dx","dy","dz"
End With
```

已封装成 MCP 工具 `cst_local_modify { shape, faceId, op, amount | dx,dy,dz, considerBlends }`。

实测（10×10×10 方块）：

```
OffsetSelectedFaces "1.5" on face 1 -> bbox hi.x 10 -> 11.5
OffsetSelectedFaces "5.0" on face 1 -> bbox hi.z 10 -> 18.0
OffsetSelectedFaces "2.0" on face 2 -> bbox lo.z 0 -> -2.0
```

三条踩坑记录：

1. **`Brick` 的 `.Name` 只写 `solid1`**，`component1:` 是引用时的前缀，写进 `.Name` 会导致整个块静默失败。
2. **`MoveSelectedFaces` 沿平面自身方向平移是无效的**（文档明说），推拉要用 `OffsetSelectedFaces`。
3. **面 ID 会变**：一次操作后新建的面会改变编号，连续操作前要重新查。

界面截图判断不可靠（视图自动缩放）。可靠做法是量：`SAT.WriteAll` 导出 → 注入代理 `restore` → `bbox`，上面的数字就是这么来的。

## 15. ACIS 侧推拉：终于跑通，以及之前为什么全空转

文档来源：`http://www-isl.ece.arizona.edu/ACIS-docs/`（**ACIS R10 第二版**，不是 2021；函数参考在
`PDF/LOP/03FN.PDF`，Local Ops 章节）。R10 的函数签名与 2021 有出入，但语义足够定位问题。

### `api_tweak_faces` 不是"移动面"

```
outcome api_tweak_faces (
    int const nface,
    FACE* face[],
    SURFACE* tool_surface[],   // 新曲面，调用方提供
    int reverse[],
    SPAposition box_low, SPAposition box_high,
    AcisOptions* ao = NULL );
```

它是"**把给定面替换成给定曲面**"。传 `tool_surface = nullptr` 就是没有目标 → 什么都不做，仍然返回 `outcome ok`。
我之前五种写法全在传 `nullptr`，所以永远空转。**问题不在 ABI，在语义。**

### `api_move_faces` 才是平移，但位移完全由 `SPAtransf` 决定

```
outcome api_move_faces (
    int const nface, FACE* face[],
    SPAtransf const& tr,          // 运动由它定义
    SPAposition box_low, SPAposition box_high,
    AcisOptions* ao = NULL );
```

我传的是默认构造的 `SPAtransf`（单位变换）→ 位移恒等于 0。而且 `box` 必须包含最终几何。

修正方式（三个导出构造函数就够了）：

```
??0SPAvector@@QEAA@NNN@Z                                   SPAvector(x,y,z)
??0SPAmatrix@@QEAA@AEBVSPAvector@@00@Z                     SPAmatrix(3 个基向量) -> 单位阵
??0SPAtransf@@QEAA@AEBVSPAmatrix@@AEBVSPAvector@@NHHH@Z    SPAtransf(矩阵, 平移向量, 1.0, 0,0,0)
```

实测（代理命令 `mv <faceIndex> dx dy dz`）：

```
block 10 10 10   -> bbox (0,0,0)-(10,10,10)
mv 0 0 0 5       -> bbox (0,0,0)-(10,10,15)     ← 面沿 +z 推了 5
```

### 关于"progressive / 失败重试"

R10 文档里没有 `retry`。有的是 `validate_lop` 选项：

- `validate_only`：只验证不执行，失败时把出问题的面和边通过 error 机制返回；
- `validate_and_lop`：先验证，失败则不执行并返回责任面/边，成功才真正执行。

这就是"可重试"的形态：先拿到失败原因（哪些面/边），改参数再调一次。配合 CST 侧的
`SetConsiderBlends` / `EnableInvertedFaceRemoval` 基本够用。