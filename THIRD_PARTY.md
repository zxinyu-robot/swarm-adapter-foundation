# 第三方依赖

| 依赖 | 用途 | 许可证 | 是否必需 |
| --- | --- | --- | --- |
| C++17 标准库、POSIX（`shm_open`、`sem_open`、pthread） | C++ 核心 | — | 是 |
| [CMake](https://cmake.org/) ≥ 3.16 | 构建 | BSD-3-Clause | 构建时 |
| [NumPy](https://numpy.org/) ≥ 1.24 | Python 本地训练 | BSD-3-Clause | Python 侧必需 |
| [Flower](https://github.com/adap/flower) ≥ 1.43, < 2 | 联邦学习 ClientApp / ServerApp | Apache-2.0 | 可选（`.[fl]`） |
| [Ray](https://github.com/ray-project/ray)（经 `flwr[simulation]`） | Flower 本机仿真 | Apache-2.0 | 可选（`.[simulation]`） |
| [pytest](https://pytest.org/)、[Ruff](https://github.com/astral-sh/ruff) | 测试与检查 | MIT | 开发时 |

`gateway/` 的可选依赖（Qwen2.5-VL、torch、transformers、ROS 2、Gazebo、Foxglove 等）见 `gateway/requirements-qwen-vl.txt` 与 `gateway/README.md`，均不属于 C++ 核心和 Python 联邦适配的依赖。

本仓库不包含第三方源码拷贝。
