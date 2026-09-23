from scripts.dataset import from_csv, to_csv


def test_csv_round_trip(constant_dataset, tmp_path):
    to_csv(constant_dataset, tmp_path)
    restored = from_csv(tmp_path)
    assert restored.model_dump() == constant_dataset.model_dump()
