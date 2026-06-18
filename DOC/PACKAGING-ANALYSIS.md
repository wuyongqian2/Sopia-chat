# Sophia Chat 打包体积与启动性能分析报告

**分析日期**: 2026-06-14
**分析范围**: PyInstaller 打包配置、依赖体积、启动链路
**实施状态**: 代码配置已落地，待重新打包验证（截至 2026-06-17）

**当前打包产物**（旧配置，未用新配置重新打包）:

| 指标 | 数值 |
|------|------|
| dist 总大小 | 1,044 MB |
| 单文件 EXE | 323 MB |
| 分发 ZIP 包 | 567 MB |
| _internal 子目录 | ~720 MB |

> ⚠️ dist 目录产物仍是旧 onefile 配置的打包结果。新配置（onedir + excludes + ONNX）已就绪但**尚未执行打包验证**（见下方第五步第 4 项）。

---

## 一、体积膨胀根因分析

### 1.1 依赖库体积 Top 10

| 排名 | 包名 | 体积 | 是否必要 | 说明 |
|------|------|------|----------|------|
| 1 | **torch** | 317 MB | 间接依赖 | torch_cpu.dll 单文件 253 MB；仅为 sentence-transformers 引入整个 PyTorch |
| 2 | **pyarrow** | 77 MB | **不必要** | 代码中无引用，来自 markitdown[all] 的传递依赖 |
| 3 | **scipy** | 52 MB | 间接依赖 | 被 sklearn/sentence-transformers 链式拉入，两个 OpenBLAS DLL 各 19 MB |
| 4 | **speech_recognition** | 42 MB | **不必要** | 代码中无使用，来自 markitdown[all] 的语音转文字功能 |
| 5 | **transformers** | 40 MB | 间接依赖 | 被 sentence-transformers 拉入，含大量训练代码 |
| 6 | **onnxruntime** | 28 MB | 必要 | OCR 引擎 RapidOCR 的运行时 |
| 7 | **numpy.libs** | 20 MB | 必要 | numpy 核心计算库 |
| 8 | **scipy.libs** | 19 MB | 间接依赖 | scipy 的 BLAS/LAPACK 底层库 |
| 9 | **PIL** | 12 MB | 必要 | 图像处理 |
| 10 | **sklearn** | 11 MB | 间接依赖 | 被 sentence-transformers 拉入 |

**关键发现**: 排名前 4 的库合计 **488 MB**，占总体积的 **68%**。其中 pyarrow (77 MB) 和 speech_recognition (42 MB) 共 **119 MB** 完全可以移除。

### 1.2 核心问题：PyTorch 的过度引入

项目使用 sentence-transformers 仅为了调用 BAAI/bge-small-zh-v1.5 模型做文本向量化（512 维 embedding）。但依赖链为：

`
sentence-transformers
  -> transformers (40 MB, 含大量训练代码)
  -> torch (317 MB, 完整深度学习框架)
  -> scipy (52 MB)
  -> sklearn (11 MB)
`

**仅 embedding 功能就引入了 ~420 MB 的依赖**。

### 1.3 markitdown[all] 引入无用重依赖

requirements.txt 中使用 markitdown[all]，all extras 会拉入：
- pyarrow (77 MB) -- Parquet 文件解析，项目未使用
- speech_recognition (42 MB) -- 音频转文字，项目未使用
- pythonnet (3 MB) -- .NET 互操作，项目未使用

**项目实际文件格式**: PDF、Word、PPT、Excel、图片、HTML、CSV、JSON、Markdown、纯文本。不需要 Parquet 和语音识别。

### 1.4 spec 文件 excludes 不完整

当前 excludes 排除了 matplotlib、pandas、cv2、PyQt5 等，但**未排除以下大型无用包**:

| 未排除的包 | 体积 | 用途 |
|-----------|------|------|
| pyarrow | 77 MB | 项目中未使用 |
| speech_recognition | 42 MB | 项目中未使用 |
| aiohttp | ~3 MB | 项目中未使用（用 requests） |
| clr_loader / pythonnet | ~3 MB | .NET 互操作，未使用 |
| redis | ~0.5 MB | 项目中未使用 |
| starlette / fastapi / uvicorn | ~2 MB | 项目用 Flask+Waitress，不需要 |
| shapely | ~3 MB | 地理空间库，未使用 |

此外，spec 中 collect_submodules 对三个包使用全量子模块收集。其中 collect_submodules(transformers) 会收集所有子模块（训练器、分布式计算、DeepSpeed 等），极大增加体积。

---

## 二、启动缓慢根因分析

### 2.1 根本原因：onefile 模式 + 巨大体积

当前 spec 中 EXE 配置：

`python
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,    # 所有二进制文件打包进 EXE
    a.zipfiles,    # 所有 zip 数据打包进 EXE
    a.datas,       # 所有数据文件打包进 EXE
    [],
    ...
)
`

这是 **onefile（单文件）模式**。每次启动时，PyInstaller bootloader 需要：

1. **解压 ~1 GB 数据到临时目录** (%TEMP%/_MEIxxxxxx/)
2. **加载 Python 解释器** (python312.dll, 7 MB)
3. **加载所有 DLL/PYD**（torch_cpu.dll 253 MB、arrow.dll 21 MB 等）
4. **执行所有顶层 import**（Flask、sentence-transformers、transformers 等）

实测预估启动耗时分解：

| 阶段 | 预估耗时 | 说明 |
|------|---------|------|
| 临时目录解压 | 5-15 秒 | 取决于磁盘速度（SSD vs HDD） |
| Python 解释器初始化 | 0.5-1 秒 | |
| torch DLL 加载 | 2-5 秒 | torch_cpu.dll 253 MB |
| transformers 初始化 | 1-3 秒 | 模型配置和 tokenizer |
| sentence-transformers 模型加载 | 3-10 秒 | 首次需下载模型 ~90 MB |
| Flask + Waitress 启动 | 0.5-1 秒 | |
| webview 窗口创建 | 1-2 秒 | |
| **总计** | **13-37 秒** | HDD 更慢 |

### 2.2 onefile 模式 vs onedir 模式

| 对比项 | onefile（当前） | onedir |
|--------|----------------|--------|
| 首次启动 | 解压全部文件到临时目录 | 直接读取，无需解压 |
| 后续启动 | 每次都重新解压 | 文件已在磁盘上 |
| 启动速度 | 慢（5-15 秒仅解压） | 快（0 秒解压） |
| 分发便利性 | 单文件，便于传输 | 整个文件夹 |
| 磁盘占用 | 临时目录 + 原始 EXE 双份 | 仅一份 |

当前 spec 同时生成了两种模式：EXE 是 onefile，COLLECT 生成 onedir 目录。但用户实际使用的是 onefile EXE。

### 2.3 Embedding 模型冷启动

cache_manager.py 中 warmup_embedding_model() 在启动时异步加载 BAAI/bge-small-zh-v1.5 模型。虽然加载是异步的，但 SentenceTransformer 初始化会触发 PyTorch 初始化（CUDA 检测等）、tokenizer 加载、模型权重加载。如果在模型就绪前有用户请求，会触发降级或阻塞。

---

## 三、优化方案

### 方案 A：最小改动，快速见效（预计减少 200-300 MB，启动提速 30-50%%）

**A1. 修复 requirements.txt**

将 markitdown[all] 改为 markitdown（去掉 pyarrow、speech_recognition 等无用依赖）。
将 sentence-transformers 改为可选依赖或使用轻量替代方案。

**A2. 补充 excludes 列表**

在 sophia_chat.spec 的 excludes 中添加以下大型无用包：
pyarrow、pyarrow.libs、speech_recognition、aiohttp、redis、starlette、fastapi、uvicorn、httptools、websockets、watchfiles、shapely、clr_loader、pythonnet、pydantic、pydantic_core、rich、typer、pyreadline3

**A3. 减少 collect_submodules 范围**

将 collect_submodules(transformers) 改为手动列出实际需要的子模块（如 transformers.models.bert、transformers.tokenization_utils）。
将 collect_submodules(sentence_transformers) 改为空列表，手动添加。

**A4. 切换为 onedir 模式**

修改 EXE 配置，不将 binaries/zipfiles/datas 打包进 EXE，改由 COLLECT 管理。用户通过 dist/Sophia Chat/Sophia Chat.exe 启动，无需每次解压。


### 方案 B：深度优化（预计减少 400-600 MB，启动提速 60-80%%）

**B1. 替换 sentence-transformers 为 ONNX Runtime 直接推理**

项目已有 onnxruntime（为 OCR 引入）。可将 bge-small-zh-v1.5 导出为 ONNX 格式，用 onnxruntime 直接推理，完全移除 PyTorch 依赖链。

替换前（需 torch + transformers + sentence-transformers = ~420 MB）：
  from sentence_transformers import SentenceTransformer
  model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
  vec = model.encode(text)

替换后（仅需 onnxruntime，已存在 = 0 额外体积）：
  import onnxruntime as ort
  session = ort.InferenceSession("bge-small-zh.onnx")

预估节省：~380 MB（torch 317 + transformers 40 + scipy 52 + sklearn 11）

**B2. 替换为更轻量的 embedding 方案**

| 方案 | 额外体积 | 说明 |
|------|---------|------|
| fastembed | ~30 MB | 基于 ONNX Runtime 的轻量 embedding 库，支持中文模型 |
| onnxruntime 直接推理 | 0 MB | 已有 onnxruntime，只需导出模型文件 |
| 移除本地 embedding | 0 MB | 改用远程 embedding API（如 OpenAI、智谱等） |

---

## 四、优化效果预估

| 优化方案 | EXE 体积 | 启动速度 | 改动量 |
|---------|---------|---------|-------|
| 当前状态 | 323 MB / dist 1044 MB | 13-37 秒 | -- |
| A. 最小改动 | ~150 MB / ~500 MB | 8-20 秒 | 小 |
| B. 深度优化 | ~60 MB / ~200 MB | 3-8 秒 | 中 |
| A+B 叠加 | ~50 MB / ~150 MB | 2-5 秒 | 中 |

---

## 五、推荐实施路径

### 第一步：配置修改（已完成）— 待打包验证

1. ✅ 将 markitdown[all] 改为 markitdown — `requirements.txt` 已改为 `markitdown`
2. ✅ 在 spec 的 excludes 中添加 pyarrow、speech_recognition、aiohttp、redis、starlette、fastapi、uvicorn、shapely、pythonnet、pydantic 等 — `sophia_chat.spec` 已补充 excludes
3. ✅ 移除 collect_submodules(transformers)，改为手动列出需要的子模块 — spec 中仅保留 `rapidocr_onnxruntime` 的 collect_submodules
4. ❌ **重新打包，验证功能正常** — 尚未执行

预期效果：体积减少约 200 MB。

### 第二步：代码替换（已完成）— 待打包验证

1. ✅ 将 bge-small-zh-v1.5 导出为 ONNX 格式 — 已使用 `LocalEmbeddingModel`（ONNX Runtime + tokenizers）
2. ✅ 用 onnxruntime 直接做 embedding 推理，替换 sentence-transformers — `cache_manager.py` 已替换
3. ✅ 从 requirements.txt 中移除 sentence-transformers、torch、transformers — 已移除
4. ✅ 切换为 onedir 打包模式 — `sophia_chat.spec` 已切换为 `exclude_binaries=True` + `COLLECT`

预期效果：进一步减少约 380 MB，启动提速显著。

### 第三步：长期优化（可选）

1. 评估 fastembed 替代方案
2. 考虑 Nuitka 编译替代 PyInstaller
3. 将 embedding 服务独立部署

---

## 六、附录：打包产物详细分析

### 6.1 _internal 子目录体积明细

| 目录 | 体积 | 说明 |
|------|------|------|
| torch/ | 317 MB | PyTorch 框架，lib/ 子目录 274 MB |
| pyarrow/ | 77 MB | Apache Arrow，完全未使用 |
| scipy/ | 52 MB | 科学计算库 |
| speech_recognition/ | 42 MB | 语音识别，完全未使用 |
| transformers/ | 40 MB | HuggingFace transformers |
| onnxruntime/ | 28 MB | OCR 引擎运行时 |
| numpy.libs/ | 20 MB | numpy BLAS 底层 |
| scipy.libs/ | 19 MB | scipy BLAS 底层 |
| PIL/ | 12 MB | Pillow 图像处理 |
| sklearn/ | 11 MB | 机器学习库 |
| cryptography/ | 9 MB | 加密库 |
| hf_xet/ | 7 MB | HuggingFace Xet |
| tokenizers/ | 7 MB | 分词器 |
| pdfminer/ | 7 MB | PDF 解析 |
| lxml/ | 6 MB | XML/HTML 解析 |
| numpy/ | 6 MB | numpy 核心 |
| pypdfium2_raw/ | 6 MB | PDF 渲染引擎 |
| pydantic_core/ | 5 MB | 数据验证 |
| pythonnet/ | 3 MB | .NET 互操作 |
| Shapely.libs/ | 3 MB | 地理空间库 |

### 6.2 最大单文件 DLL/PYD

| 文件 | 体积 | 归属 |
|------|------|------|
| torch_cpu.dll | 253 MB | PyTorch |
| arrow.dll | 21 MB | PyArrow |
| libscipy_openblas*.dll | 19 MB x2 | SciPy |
| torch_python.dll | 17 MB | PyTorch |
| onnxruntime_pybind11_state.pyd | 15 MB | ONNX Runtime |
| onnxruntime.dll | 12 MB | ONNX Runtime |
| arrow_flight.dll | 12 MB | PyArrow |
| arrow_compute.dll | 9 MB | PyArrow |
| hf_xet.pyd | 7 MB | HuggingFace Xet |
| tokenizers.pyd | 7 MB | HuggingFace Tokenizers |

仅 torch_cpu.dll + 两个 OpenBLAS DLL + arrow.dll 就占了 **312 MB**。

---

## 七、结论

打包体积膨胀的三个核心原因：

1. **PyTorch 过度引入**（317 MB）：仅为本地 embedding 功能就引入了完整的深度学习框架
2. **markitdown[all] 无用传递依赖**（119 MB）：pyarrow 和 speech_recognition 在代码中完全未使用
3. **spec excludes 不完整**：多个大型无用包未被排除

启动缓慢的两个核心原因：

1. **onefile 模式**：每次启动需解压 ~1 GB 数据到临时目录
2. **PyTorch DLL 加载**：torch_cpu.dll 253 MB 的 DLL 加载耗时显著

通过分步优化，可以将体积从 1 GB 压缩到 150-200 MB，启动时间从 13-37 秒缩短到 3-8 秒。
