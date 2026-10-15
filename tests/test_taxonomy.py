import pytest

from backend.core import config


@pytest.fixture
def taxonomy_dir(tmp_path, monkeypatch):
    source = config.CONFIG_DIR / "taxonomy.default.json"
    original = source.read_bytes()
    (tmp_path / "taxonomy.default.json").write_bytes(original)
    (tmp_path / "taxonomy.json").write_bytes(original)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    return tmp_path


def editable(taxonomy):
    return {group: config.taxonomy_rows(taxonomy, group) for group in config.TAXONOMY_GROUPS}


@pytest.mark.parametrize("name,expected", [("Đời sống & sức khỏe", "doi_song_suc_khoe"), ("  Câu hỏi?  ", "cau_hoi"), ("DƯỢC LIỆU", "duoc_lieu"), ("🌿", "nhan")])
def test_vietnamese_code_generation(name, expected):
    assert config.label_code(name, set()) == expected
    assert config.label_code(name, {expected, expected + "_2"}) == expected + "_3"


def test_save_preserves_codes_and_restores_escapes(taxonomy_dir):
    original = config.load_taxonomy()
    groups = editable(original)
    code = groups["topic"][0]["code"]
    groups["topic"][0]["name"] = "Tên đã đổi"
    groups["topic"].append({"name": "Câu hỏi", "description": "Chủ đề hỏi đáp về thuốc"})
    saved = config.save_taxonomy(groups)
    assert saved["labels"][code] == "Tên đã đổi"
    assert saved["topic"]["cau_hoi_2"] == "Chủ đề hỏi đáp về thuốc"
    for group in config.TAXONOMY_GROUPS:
        assert saved[group]["khac"] == original[group]["khac"]
        assert list(saved[group])[-1] == "khac"
        assert all(saved["labels"][code] for code in saved[group])
    assert saved["cta"]["khong_co"] == original["cta"]["khong_co"]
    assert saved["labels"]["risk_absolute"] == original["labels"]["risk_absolute"]
    assert config.load_taxonomy() == saved
    config.reset_taxonomy()
    assert (taxonomy_dir / "taxonomy.json").read_bytes() == (taxonomy_dir / "taxonomy.default.json").read_bytes()


@pytest.mark.parametrize("invalid", ["name", "description", "duplicate", "too_few", "escape_name"])
def test_invalid_rows_leave_file_unchanged(taxonomy_dir, invalid):
    before = (taxonomy_dir / "taxonomy.json").read_bytes()
    groups = editable(config.load_taxonomy())
    if invalid in {"name", "description"}:
        groups["topic"][0][invalid] = "   "
    elif invalid == "duplicate":
        groups["topic"][1]["name"] = groups["topic"][0]["name"].upper()
    elif invalid == "escape_name":
        groups["topic"][0]["name"] = "Khác"
    else:
        groups["topic"] = groups["topic"][:1]
    with pytest.raises(ValueError):
        config.save_taxonomy(groups)
    assert (taxonomy_dir / "taxonomy.json").read_bytes() == before
