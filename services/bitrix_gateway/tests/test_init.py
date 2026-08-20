from bitrix_gateway import main


def test_package_import() -> None:
    assert callable(main)