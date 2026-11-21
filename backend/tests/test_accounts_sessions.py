"""'Sign out other devices', ending single sessions and changing the password."""

from apps.accounts.models import UserSession

from .conftest import PASSWORD, delete, post, sign_in

NEW_PASSWORD = "a-brand-new-passphrase-42"


def second_device(new_client, user, agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17) Safari/604.1"):
    client = new_client()
    response = sign_in(client, user.username, HTTP_USER_AGENT=agent)
    assert response.status_code == 200
    return client


# --- Listing -----------------------------------------------------------------


def test_sessions_list_shows_all_my_devices_and_marks_the_current_one(signed_in, new_client):
    user, laptop = signed_in("alice")
    phone = second_device(new_client, user)

    results = laptop.get("/api/v1/auth/sessions/").json()["results"]

    assert len(results) == 2
    assert sum(item["is_current"] for item in results) == 1
    assert {item["device_label"] for item in results} >= {"Safari on iPhone"}
    # From the phone, the flag moves.
    from_phone = phone.get("/api/v1/auth/sessions/").json()["results"]
    current = next(item for item in from_phone if item["is_current"])
    assert current["device_label"] == "Safari on iPhone"


def test_sessions_list_never_exposes_session_keys_or_other_users(signed_in, new_client, make_user):
    user, client = signed_in("alice")
    bob = make_user("bob")
    second_device(new_client, bob)
    keys = list(UserSession.objects.values_list("session_key", flat=True))

    response = client.get("/api/v1/auth/sessions/")

    assert len(response.json()["results"]) == 1  # only my own
    text = response.content.decode()
    assert all(key not in text for key in keys)
    assert "session_key" not in text


# --- Ending sessions ---------------------------------------------------------


def test_ending_another_session_takes_effect_immediately(signed_in, new_client):
    user, laptop = signed_in("alice")
    phone = second_device(new_client, user)
    phone_id = next(
        s["id"]
        for s in laptop.get("/api/v1/auth/sessions/").json()["results"]
        if not s["is_current"]
    )

    response = delete(laptop, f"/api/v1/auth/sessions/{phone_id}/")

    assert response.status_code == 204
    assert phone.get("/api/v1/auth/me/").status_code == 401  # signed out at once
    assert laptop.get("/api/v1/auth/me/").status_code == 200
    ended = UserSession.objects.get(pk=phone_id)
    assert ended.ended_reason == "SIGNED_OUT_BY_USER" and ended.ended_at is not None


def test_cannot_end_the_session_you_are_using_this_way(signed_in):
    user, client = signed_in("alice")
    current_id = client.get("/api/v1/auth/sessions/").json()["results"][0]["id"]

    response = delete(client, f"/api/v1/auth/sessions/{current_id}/")

    assert response.status_code == 400
    assert client.get("/api/v1/auth/me/").status_code == 200


def test_cannot_end_another_users_session(signed_in, new_client, make_user):
    _, alice = signed_in("alice")
    bob = make_user("bob")
    bob_client = second_device(new_client, bob)
    bob_session = UserSession.objects.get(user=bob)

    response = delete(alice, f"/api/v1/auth/sessions/{bob_session.pk}/")

    assert response.status_code == 404
    assert bob_client.get("/api/v1/auth/me/").status_code == 200  # untouched


def test_ending_an_unknown_session_is_not_found(signed_in):
    _, client = signed_in("alice")
    response = delete(client, "/api/v1/auth/sessions/6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11/")
    assert response.status_code == 404


def test_sign_out_other_devices_keeps_only_the_current_one(signed_in, new_client, make_user):
    user, laptop = signed_in("alice")
    phone = second_device(new_client, user)
    tablet = second_device(new_client, user)
    other_user = make_user("bob")
    bob_client = second_device(new_client, other_user)

    response = post(laptop, "/api/v1/auth/sessions/end-others/")

    assert response.status_code == 200 and response.json() == {"ended": 2}
    assert phone.get("/api/v1/auth/me/").status_code == 401
    assert tablet.get("/api/v1/auth/me/").status_code == 401
    assert laptop.get("/api/v1/auth/me/").status_code == 200
    assert bob_client.get("/api/v1/auth/me/").status_code == 200  # other users unaffected
    assert len(laptop.get("/api/v1/auth/sessions/").json()["results"]) == 1


def test_sign_out_other_devices_with_no_others_is_harmless(signed_in):
    _, client = signed_in("alice")
    assert post(client, "/api/v1/auth/sessions/end-others/").json() == {"ended": 0}


# --- Changing the password ---------------------------------------------------


def test_change_password_ends_other_sessions_and_keeps_this_one(signed_in, new_client):
    user, laptop = signed_in("alice", must_change_password=True)
    phone = second_device(new_client, user)

    response = post(
        laptop,
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200 and response.json()["ended_other_sessions"] == 1
    assert phone.get("/api/v1/auth/me/").status_code == 401
    assert laptop.get("/api/v1/auth/me/").status_code == 200  # still signed in here
    mine = laptop.get("/api/v1/auth/sessions/").json()["results"]
    assert len(mine) == 1 and mine[0]["is_current"]  # our record followed the rotated key

    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD) and not user.check_password(PASSWORD)
    assert user.must_change_password is False
    assert user.password_changed_at is not None
    assert sign_in(new_client(), "alice", PASSWORD).status_code == 401
    assert sign_in(new_client(), "alice", NEW_PASSWORD).status_code == 200


def test_change_password_needs_the_current_password(signed_in):
    user, client = signed_in("alice")
    response = post(
        client,
        "/api/v1/auth/password/change/",
        {"current_password": "wrong-current-password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert "current_password" in response.json()["error"]["details"]
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_change_password_enforces_the_policy(signed_in):
    user, client = signed_in("alice")
    for weak in ("short1", "password1234", "12345678901234", "alice@example.org"):
        response = post(
            client,
            "/api/v1/auth/password/change/",
            {"current_password": PASSWORD, "new_password": weak},
        )
        assert response.status_code == 400, weak
        assert "new_password" in response.json()["error"]["details"]
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_new_password_must_differ_from_the_current_one(signed_in):
    _, client = signed_in("alice")
    response = post(
        client,
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert response.status_code == 400
    assert "new_password" in response.json()["error"]["details"]
