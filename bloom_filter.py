    #计算布隆过滤器的哈希位置，布隆过滤器的操作函数
import math
import hashlib

import json
from pathlib import Path

class BloomFilter:


    def __init__(self, capacity: int, error_rate: float):

        #规定文本容量和误判率的格式
        if capacity <= 0:
            raise ValueError("capacity 必须大于 0")

        if not 0 < error_rate < 1:
            raise ValueError("error_rate 必须在 0 和 1 之间")


        # 1. 保存初始化参数
        self.capacity = capacity
        self.error_rate = error_rate

        # 2. 计算位数组长度
        self.bit_size = math.ceil(
            -capacity * math.log(error_rate)
            / (math.log(2) ** 2)
        )

        # 3. 计算哈希函数数量
        self.hash_count = math.ceil(
            (self.bit_size / capacity) * math.log(2)
        )

        # 4. 创建位数组
        self.bits = bytearray(
            math.ceil(self.bit_size / 8)
        )


    def _validate_item(self, item: object) -> None:

        # 1. 检查数据类型
        if not isinstance(item, str):
            raise TypeError("item 必须是字符串")

        # 2. 检查是否为空或只有空白字符
        if not item.strip():
            raise ValueError("item 不能为空")


        #双重哈希函数生成位置
    def _get_positions(self, item: str):

        # 先检查输入是否合法
        self._validate_item(item)

        # 1. 对元素进行一次 SHA-256 计算
        content = item.encode("utf-8")

        digest = hashlib.sha256(content).digest()

        # 2. 从哈希结果中提取两个基础哈希值
        h1 = int.from_bytes(
            digest[:8],
            byteorder="big"
        )

        h2 = int.from_bytes(
            digest[8:16],
            byteorder="big"
        )

        # 3. 将第二个哈希值限制在合理范围
        h2 = h2 % self.bit_size

        if h2 == 0:
            h2 = 1

        # 确保 h2 与位数组长度互质
        while math.gcd(h2, self.bit_size) != 1:
            h2 += 1

            if h2 >= self.bit_size:
                h2 = 1

        # 4. 根据双重哈希公式生成多个位置
        positions = []

        for i in range(self.hash_count):

            position = (
                h1 + i * h2
            ) % self.bit_size

            positions.append(position)

        return positions


    # 添加id元素
    def add(self, item: str):

        positions = self._get_positions(item)

        for position in positions:

            byte_index = position // 8

            bit_index = position % 8

            self.bits[byte_index] |= (
                1 << bit_index
            )

    # 判断元素是否可能存在
    def contains(self, item: str):

        positions = self._get_positions(item)

        for position in positions:

            byte_index = position // 8

            bit_index = position % 8

            if not (
                self.bits[byte_index]
                & (1 << bit_index)
            ):
                return False

        return True


        #保存好旧的json数据
    def save(self, file_path: str):

        # 1. 整理需要保存的数据
        data = {
            "version": 1,
            "capacity": self.capacity,
            "error_rate": self.error_rate,
            "bit_size": self.bit_size,
            "hash_count": self.hash_count,
            "bits": self.bits.hex()
        }

        # 2. 转换成 JSON 并写入文件
        Path(file_path).write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8"
        )

        #读取磁盘快照，恢复布隆，从json中恢复，不需要测试计算对应的位置
    @classmethod
    def load(cls, file_path: str):

        # 1. 读取 JSON 文件
        data = json.loads(
            Path(file_path).read_text(encoding="utf-8")
        )

        # 2. 检查数据版本
        if data["version"] != 1:
            raise ValueError("不支持的布隆过滤器数据版本")

        # 3. 根据保存的参数重新创建对象
        bf = cls(
            data["capacity"],
            data["error_rate"]
        )

        # 4. 检查配置是否一致
        if (
            data["bit_size"] != bf.bit_size
            or data["hash_count"] != bf.hash_count
        ):
            raise ValueError("布隆过滤器配置不一致")

        # 5. 恢复位数组
        bits = bytearray.fromhex(data["bits"])

        if len(bits) != len(bf.bits):
            raise ValueError("位数组长度不正确")

        bf.bits = bits

        return bf


        #更新布隆过滤器，根据原始文档重新构建，过滤器扩容之后需要重新计算新的id对应位置
    @classmethod
    def from_items(
        cls,
        items,
        capacity: int,
        error_rate: float
    ):
        # 1. 创建一个新的布隆过滤器
        bf = cls(capacity, error_rate)

        # 2. 将原始文档重新添加
        for item in items:
            bf.add(item)

        # 3. 返回重建后的过滤器
        return bf
