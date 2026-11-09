"""swarm_adapter 的 Python 侧：特征、端侧记录读取、本地训练和 Flower 适配。

与 C++17 核心以两份文件为边界交互：
- C++ RingStrategyStore 写出的 JSONL 分段文件（records）；
- 策略文件（policy_file），Python 写、C++ FilePolicyClient 读。
"""

__version__ = "0.1.0"
