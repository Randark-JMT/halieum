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
  -> 将 exp 与本地 UTC 时间比较
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
```

输出永远不会使用 `print` (宿主程序可以劫持它)；诊断信息直接写入 `sys.stderr`，除非 `debug=True`，否则保持静默。

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
- 删除**仅**发生在许可证可被证明无效时：一份签名正确但已过期的许可证，或签名 /id无法通过验证的许可证。
- 清除目标会对照一份拒绝清单进行筛查，涵盖**文件系统根、关键系统目录、正在运行的解释器、site-packages 以及 halieum 自身的包目录**。位于项目根目录之外的目标会被拒绝。
- `.git`/`.hg`/`.svn` 会被保留；每一处文件删除都单独设防（Windows 上被锁定的文件会被跳过，而非致命错误）。
- 任何 **halieum 内部错误**都只会导致空操作，绝不删除。
- `dry_run=True` 会禁用一切破坏性操作与一切退出。
- `import halieum` 是惰性的；在调用 `init()` 之前什么都不运行，且同一个 `id` 在每个进程中只会被处理一次。

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
