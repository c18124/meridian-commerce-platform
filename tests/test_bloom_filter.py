from bloom_filter import BloomFilter
import pytest

def test_add_and_contains():

    bf = BloomFilter(1000, 0.01)

    bf.add("python_notes.txt")

    assert bf.contains("python_notes.txt") is True


def test_unknown_item_returns_false():

    bf = BloomFilter(1000, 0.01)

    assert bf.contains("unknown.txt") is False


def test_double_hash_generates_correct_count():

    bf = BloomFilter(1000, 0.01)

    positions = bf._get_positions("python_notes.txt")

    assert len(positions) == bf.hash_count

#强期望测试，有可能哈希碰撞
def test_double_hash_positions_are_unique():

    bf = BloomFilter(1000, 0.01)

    positions = bf._get_positions("python_notes.txt")

    assert len(set(positions)) == len(positions)



@pytest.mark.parametrize("capacity", [0, -1, -100])
def test_invalid_capacity(capacity):

    with pytest.raises(ValueError):
        BloomFilter(capacity, 0.01)


@pytest.mark.parametrize(
    "error_rate",
    [0, 1, -0.1, 1.5]
)
def test_invalid_error_rate(error_rate):

    with pytest.raises(ValueError):
        BloomFilter(1000, error_rate)

    #
@pytest.mark.parametrize("item", ["", " ", "   ", "\t"])
def test_add_rejects_empty_item(item):

    bf = BloomFilter(1000, 0.01)

    with pytest.raises(ValueError):
        bf.add(item)


@pytest.mark.parametrize("item", ["", " ", "   "])
def test_contains_rejects_empty_item(item):

    bf = BloomFilter(1000, 0.01)

    with pytest.raises(ValueError):
        bf.contains(item)


@pytest.mark.parametrize("item", [123, None, [], {}])
def test_add_rejects_invalid_type(item):

    bf = BloomFilter(1000, 0.01)

    with pytest.raises(TypeError):
        bf.add(item)


def test_duplicate_add_is_idempotent():

    bf = BloomFilter(1000, 0.01)

    bf.add("python_notes.txt")

    # 保存第一次添加后的位数组
    original_bits = bytes(bf.bits)

    # 重复添加
    bf.add("python_notes.txt")
    bf.add("python_notes.txt")

    # 位数组应该保持不变
    assert bytes(bf.bits) == original_bits

    assert bf.contains("python_notes.txt")



def test_save_and_load_preserves_data(tmp_path):

    # 1. 创建布隆过滤器
    bf = BloomFilter(1000, 0.01)

    # 2. 添加文档
    bf.add("python_notes.txt")
    bf.add("project_intro.txt")

    # 3. 保存到临时 JSON 文件
    file_path = tmp_path / "bloom.json"

    bf.save(str(file_path))

    # 4. 重新加载，创建新的对象
    loaded_bf = BloomFilter.load(str(file_path))

    # 5. 验证原来的数据仍然存在
    assert loaded_bf.contains("python_notes.txt")
    assert loaded_bf.contains("project_intro.txt")

    # 6. 验证位数组恢复一致
    assert loaded_bf.bits == bf.bits


def test_load_rejects_unsupported_version(tmp_path):

    file_path = tmp_path / "bloom.json"

    file_path.write_text(
        '{"version": 999}',
        encoding="utf-8"
    )

    with pytest.raises(ValueError):
        BloomFilter.load(str(file_path))


    #测试新生成的布隆过滤器参数和写入的文档
def test_from_items_rebuilds_filter():

    # 1. 准备原始文档
    documents = [
        "python_notes.txt",
        "project_intro.txt",
        "rag_guide.txt"
    ]

    # 2. 根据原始文档重建过滤器
    bf = BloomFilter.from_items(
        documents,
        capacity=5000,
        error_rate=0.01
    )

    # 3. 检查新过滤器的配置
    assert bf.capacity == 5000
    assert bf.error_rate == 0.01

    # 4. 检查所有原始文档仍然能够被找到
    for item in documents:
        assert bf.contains(item) is True

    #测试从新建到写入json再到重新从json加载一条生态链的流程完整性
def test_rebuilt_filter_can_be_saved_and_loaded(tmp_path):

    documents = [
        "python_notes.txt",
        "project_intro.txt",
        "rag_guide.txt"
    ]

    # 1. 重建过滤器
    bf = BloomFilter.from_items(
        documents,
        capacity=5000,
        error_rate=0.01
    )

    # 2. 保存新过滤器
    file_path = tmp_path / "rebuilt_bloom.json"
    bf.save(str(file_path))

    # 3. 重新加载
    loaded_bf = BloomFilter.load(str(file_path))

    # 4. 验证原始文档
    for item in documents:
        assert loaded_bf.contains(item) is True

    # 5. 验证容量
    assert loaded_bf.capacity == 5000
