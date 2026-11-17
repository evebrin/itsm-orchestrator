import pytest
import requests

from itsm.platform import settings
from itsm.platform.audit import Audit
from itsm.platform.sn import Hibernating, SNClient, SNError
from tests.unit.fakes import FakeResp, FakeSession

PDI = "https://dev000001.service-now.com"


def client(tmp_path, session, password="s3cret-pass"):
    return SNClient(PDI, "u", password, identity="t", audit=Audit(tmp_path / "a.jsonl"), session=session, sleep=lambda s: None)


def test_settings_refuses_non_pdi_and_names_missing_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SN_INSTANCE_URL=https://example.com\n")
    with pytest.raises(settings.SettingsError, match="not a Personal Developer Instance"):
        settings.load(env)
    env.write_text(f"SN_INSTANCE_URL={PDI}\nSN_ADMIN_PASSWORD=topsecret\n")
    with pytest.raises(settings.SettingsError) as e:
        settings.load(env, required=("SN_INSTANCE_URL", "SN_ADMIN_USER"))
    assert "SN_ADMIN_USER" in str(e.value) and "topsecret" not in str(e.value)
    s = settings.load(env)
    assert s.secrets() == ["topsecret"] and "topsecret" not in repr(s)


def test_client_refuses_other_hosts(tmp_path):
    with pytest.raises(SNError):
        SNClient("https://evil.example.com", "u", "p", identity="t", audit=Audit(tmp_path / "a.jsonl"))


def test_hibernating_pdi_is_detected(tmp_path):
    c = client(tmp_path, FakeSession({("GET", "/api/now/table"): FakeResp(200, html=True)}))
    with pytest.raises(Hibernating):
        c.list("incident", purpose="t")


def test_errors_are_redacted(tmp_path):
    c = client(tmp_path, FakeSession({("GET", "/api/now/table"): FakeResp(500, {"echo": "s3cret-pass"})}))
    with pytest.raises(SNError) as e:
        c.list("incident", purpose="t")
    assert "s3cret-pass" not in str(e.value) and "***" in str(e.value)


def test_dropped_write_is_not_retried_but_dropped_read_is(tmp_path):
    class Dropping(FakeSession):
        def request(self, method, url, **kw):
            self.calls.append(method)
            raise requests.ConnectionError("dropped")
    s = Dropping()
    c = client(tmp_path, s)
    with pytest.raises(SNError):
        c.update("incident", "x", {"a": 1}, purpose="t")
    assert s.calls == ["PATCH"]
    s.calls.clear()
    with pytest.raises(SNError):
        c.list("incident", purpose="t")
    assert s.calls == ["GET", "GET", "GET"]


def test_refusals_are_returned_and_every_call_is_audited(tmp_path):
    c = client(tmp_path, FakeSession({("POST", "/api/sn_chg_rest"): FakeResp(403, {"error": "no"})}))
    status, _ = c.request("POST", "/api/sn_chg_rest/change/normal", purpose="must be refused", json={})
    assert status == 403
    assert c.audit.rows[-1]["identity"] == "t" and c.audit.rows[-1]["result"] == "403"
