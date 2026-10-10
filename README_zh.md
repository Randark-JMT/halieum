# halieum

一个极简的、**零依赖**的个人 Python 项目许可证防护工具。

[English](README.md) | 中文

```python
import halieum
halieum.init("your-license-id")
```

`import halieum` 本身**什么都不做** —— 无网络请求、无文件读写、无输出、不做任何猴子补丁。它不会影响周围的代码。所有逻辑都在 `init()` 内部运行。

当 `id` 对应的许可证被**确认无效**时（一份签名有效但已过期的许可证，或被篡改 / 伪造的许可证），halieum 会从**项目根目录**开始执行清除。而当许可证服务器仅仅是**无法访问**时，它绝不会删除任何内容：它会回退到本地缓存；若是首次运行且没有缓存，则直接退出宿主程序。

> halieum 是作者为自身项目设置的一道威慑。任何能编辑源码的人都可以删掉上面那两行代码；请把它当作减速带，而不是保险柜。

---

## 工作原理

```
init(id)
  -> GET  <PAGES_BASE>/licenses/<id>.json           (GitHub Pages)
  -> 用内嵌的公钥验证 RSA (PKCS#1 v1.5 + SHA-256) 签名
  -> 解析当前时间（默认走 NTP；仅在失败时回退本地时钟）
  -> 将 exp 与该权威时间比较
       有效且未过期        -> 缓存到临时目录，静默返回
       过期 / 被篡改       -> 执行清除(删除)，随后退出
  -> 若网络请求失败：
       有缓存且有效        -> 静默返回
       有缓存但过期        -> 执行清除(删除)，随后退出
       无缓存(首次运行)  -> 退出宿主程序(绝不删除)
```

签名机制刻意采用非对称设计：**公钥**随包分发（在 PyPI 上公开也无妨 —— 它只能用于验证），而**私钥**保存在 GitHub Actions 的 secret 中，用于为每一份许可证签名。

---

## 安装

```bash
pip install halieum
```

运行时**仅依赖标准库**，目标支持 **Python 3.6+**。

---

## `init()` API

```python
halieum.init(
    id,                 # 必填。由 Action 签发的许可证标识符。
    dry_run=False,      # 仅判定有效性；不删除、不退出。
    debug=False,        # 记录到 sys.stderr(绝不 print)。默认：静默。
    mode="recursive",   # "recursive" | "source" | "self" | "file"
    target=None,        # 执行清除的目录/文件。默认：项目根目录。
    root=None,          # 覆盖项目根目录的自动探测。
    extensions=None,    # 自定义扩展名过滤(隐含启用源码过滤)。
    timeout=None,       # 网络超时时间(秒)，默认 5.0。
    exit_after=True,    # 执行破坏性清除后退出进程。
    ntp=True,           # 通过 NTP 校验时间，而非本地时钟（默认）。
    ntp_servers=None,   # 自定义 NTP 服务器（默认：内置权威列表）。
    ntp_timeout=None,   # 单个 NTP 服务器超时（秒），默认 5.0。
    ntp_fallback=None,  # NTP 不可达时："local"（默认）| "strict"。
    recheck_interval=None,  # 可选：每 N 秒在守护线程中重新校验一次。
)
```

**模式**

| 模式              | 效果                                                                |
| --------------- | ----------------------------------------------------------------- |
| `recursive`(默认) | 删除 `target`(默认：项目根目录) 下的所有文件，随后移除清空后的目录。`.git`/`.hg`/`.svn` 会被保留。 |
| `source`        | 与 `recursive` 类似，但仅删除扩展名在 `extensions` 中的文件 (默认：常见源码扩展名)。         |
| `self`          | 仅删除调用 `init()` 的那一个文件。                                            |
| `file`          | 仅删除解析后的单个 `target` 文件。                                            |

**项目根目录**指入口脚本所在目录 (`__main__.__file__`，否则 `sys.argv[0]`)，并回退到当前工作目录。因此即便从子模块中调用 `init()`，也始终解析到项目根目录 —— 既不是子模块所在目录，也不是已安装的包目录。

**示例**

```python
# 仅检查，不改动任何东西，打印诊断信息：
halieum.init("my-id", dry_run=True, debug=True)

# 失败时仅删除 ./src 目录树：
halieum.init("my-id", target="src")

# 失败时仅删除源码文件，保留数据/资源：
halieum.init("my-id", mode="source")

# 失败时仅删除调用 init() 的那个文件：
halieum.init("my-id", mode="self")

# 要求权威 NTP 时间；若无法获取则拒绝运行：
halieum.init("my-id", ntp_fallback="strict")

# 使用你自己的 NTP 服务器：
halieum.init("my-id", ntp_servers=["time.internal.example.com"])

# 长时间运行的进程：每小时复检一次，许可证过期即停止：
halieum.init("my-id", recheck_interval=3600)
```

输出永远不会使用 `print` (宿主程序可以劫持它)；诊断信息直接写入 `sys.stderr`，除非 `debug=True`，否则保持静默。

---

## 时间校验与防时钟篡改

过期校验的可信度取决于它所读取的时钟。如果 halieum 用**本地**系统时间去比较 `exp`，攻击者只需把时钟往回拨，就能继续运行已过期的许可证。因此 halieum 默认通过 UDP/123 从**权威公共 NTP 服务器**读取当前时间：

```
time.cloudflare.com   time.google.com   pool.ntp.org   time.windows.com
time.apple.com        ntp.aliyun.com    cn.pool.ntp.org   ntp.ntsc.ac.cn
```

它们会按顺序尝试，第一个应答的服务器生效；可用 `ntp_servers` 覆盖该列表。其行为如下：

- **NTP 可达** → 由 NTP 时间判定是否过期，因此本地时钟被回拨（或走快）都会被忽略。
- **NTP 不可达** → halieum 回退到本地时钟，但绝不会让它读得*早于*上次 NTP 成功时缓存的可信高水位标记 —— 因此即便离线，把时钟拨回到上次校验时间之前仍会被识别。
- **`ntp_fallback="strict"`** → 若无法获得权威时间，halieum 会退出宿主程序（退出码 `77`），而不是信任一个可能被篡改的时钟。此情况下不会删除任何文件。

如需关闭并仅使用本地时钟（旧有行为），设置 `ntp=False` 即可。NTP 需要出站 UDP/123；若你的运行环境屏蔽了它，可以放行、把 `ntp_servers` 指向可达的内网服务器，或传入 `ntp=False`。

---

## 长时间任务与后台复检看门狗

`init()` 只在**启动时**校验一次许可证。因此一个长时间运行的宿主 —— `while True` 循环、服务器、异步 worker —— 可能会「活得比许可证更久」：在它持续运行期间，没有任何东西再去检查是否已过期。

传入 `recheck_interval=N` 即可启用。halieum 会为**每个许可证 id 启动一个守护线程**，每 `N` 秒用完全相同的设置（NTP、超时、mode、root）重新校验一次。若某次复检**确认**许可证已 EXPIRED（过期）或 TAMPERED（被篡改），它会执行与启动时相同的清除，然后硬退出进程：

```python
# 每小时复检一次；若期间许可证已过期，则停止进程：
halieum.init("my-id", recheck_interval=3600)
```

要点：

- **可选，默认关闭。** `recheck_interval=None`（默认）只在启动时检查一次 —— 除非你主动开启，否则行为完全不变。
- **硬退出（`os._exit`）。** 看门狗运行在后台线程，而 `sys.exit()` 在该线程只会结束它自己，主循环照跑不误。`os._exit()` 会立即终止整个解释器 —— 这才是真正能停下 `while True` 的手段。注意它会跳过 `finally`/`atexit` 且不刷新缓冲区，因此进行中的写入可能被截断。
- **绝不会因瞬时故障被杀。** 只有**确认**的 EXPIRED/TAMPERED 才会动作。短暂的网络失败（`NETFAIL_NOCACHE`）或时钟不可信（`TIME_UNVERIFIED`）都是空操作，因此一次网络抖动不会拖垮长时间任务。
- **间隔下限。** 小于 `60` 秒的值会被向上钳制到 `60`，避免疯狂请求许可证服务器与 NTP 池。
- **遵循 `exit_after`。** 当 `exit_after=False` 时，看门狗会执行清除（删除）但让进程继续运行。
- **`dry_run` 下不启动。** `dry_run=True` 绝不会派生看门狗。
- **每个 id 一个线程。** 对同一 id 反复调用 `init()` 不会叠加看门狗线程，且 `import halieum` 仍是惰性的（看门狗模块在 `init()` 内部延迟导入）。

---

## 搭建你自己的许可证服务器 (一次性)

签名密钥、签发 Action 与 Pages 分发都在本仓库内。

### 1. 生成 RSA 密钥对

```bash
pip install pycryptodome
python tools/gen_keys.py
```

这会用你的**公钥**重写 `src/halieum/_keys.py`，并将**私钥** (PEM) 打印到 stdout。

### 2. 将私钥存储为 secret

仓库 → Settings → Secrets and variables → Actions → New repository secret：

- Name: `HALIEUM_SIGNING_KEY`
- Value: 上面打印出的 PEM 私钥

> 在生成真实公钥之前，`_keys.py` 携带的是一个占位符 (`n = 0`)，halieum 保持
> **惰性** (它会上报 "unconfigured" 且从不执行清除)。

### 3. 启用 GitHub Pages

仓库 → Settings → Pages → **Source: GitHub Actions**。

在 `src/halieum/_config.py` 中设置你的 Pages 基础 URL：

```python
DEFAULT_BASE = "https://<your-username>.github.io/<repo>/"
```

此后许可证将通过 `<DEFAULT_BASE>licenses/<id>.json` 提供。

### 4. 签发一份许可证

仓库 → Actions → **Issue License** → Run workflow，并提供：

- `id` —— 许可证标识符 (与传给 `init()` 的字符串一致)。
- `datetime` —— 过期时间，ISO-8601 UTC，例如 `2026-12-31T23:59:59Z`。

该 workflow 会为许可证签名，写入 `licenses/<id>.json`，将其作为事实来源提交回仓库，并把所有许可证部署到 Pages。**以相同的 `id` 重新运行会更新其 `datetime`** 并重新签名。

---

## 安全保证

halieum 刻意倾向&#x4E8E;_&#x4E0D;_&#x5220;除：

- **仅有网络故障绝不触发删除**。它会使用缓存，或 (首次运行时) 退出宿主程序。
- **默认以权威 NTP 时间判定是否过期**，因此回拨本地时钟无法让已过期的许可证复活。当 NTP 不可达时，本地时钟会被限制在不早于可信高水位标记；`ntp_fallback="strict"` 则会在无法取得权威时间时退出宿主程序，而不是臆断。
- 删除**仅**发生在许可证可被证明无效时：一份签名正确但已过期的许可证，或签名 /id无法通过验证的许可证。
- 清除目标会对照一份拒绝清单进行筛查，涵盖**文件系统根、关键系统目录、正在运行的解释器、site-packages 以及 halieum 自身的包目录**。位于项目根目录之外的目标会被拒绝。
- `.git`/`.hg`/`.svn` 会被保留；每一处文件删除都单独设防（Windows 上被锁定的文件会被跳过，而非致命错误）。
- 任何 **halieum 内部错误**都只会导致空操作，绝不删除。
- `dry_run=True` 会禁用一切破坏性操作与一切退出。
- `import halieum` 是惰性的；在调用 `init()` 之前什么都不运行，且同一个 `id` 在每个进程中只会被处理一次。
- 后台复检看门狗为**可选**（`recheck_interval`）；默认绝不启动，且运行途中的瞬时网络故障或时钟不可信绝不会停止宿主 —— 只有确认的 EXPIRED/TAMPERED 才会。

---

## 开发

```bash
pip install -e ".[dev]"      # 可编辑安装 + pytest/build/twine
pytest -q                    # 运行测试套件(仅标准库；无需加密)
python -m build              # sdist + wheel
twine check dist/*
```

测试套件使用嵌入在 `tests/conftest.py` 中、由纯 Python 生成的**一次性** RSA 密钥进行签名，因此无需任何第三方加密库。CI (`.github/workflows/ci.yml`) 在 Ubuntu 和 Windows上跨 Python 3.8–3.14 运行矩阵测试。

### 发布到 PyPI

```bash
python -m build
twine upload dist/*
```

---

## 许可证

MIT —— 参见 [LICENSE](LICENSE)。
