import pytest

from tutor_api.settings import Settings


def test_settings_repr_does_not_expose_connection_or_pseudonym_secret():
    configured = Settings(
        database_url="mysql+pymysql://user:PRIVATE-DB-PASSWORD@127.0.0.1/test",
        pseudonym_secret="PRIVATE-PSEUDONYM-KEY",
    )
    assert "PRIVATE-DB-PASSWORD" not in repr(configured)
    assert "PRIVATE-PSEUDONYM-KEY" not in repr(configured)


def test_invalid_startup_settings_do_not_echo_input_values():
    with pytest.raises(ValueError) as error:
        Settings(local_identity_mock=True, env="staging", pseudonym_secret="PRIVATE-PSEUDONYM-KEY")
    assert "input_value" not in str(error.value)
    assert "PRIVATE-PSEUDONYM-KEY" not in str(error.value)
