import base64
import flask
import nose
import za.biz as biz
import za.biz.accounts
import za.test.biz
import za.blueprints.biz_api as module
import za.util

# note that a request has its own session; session.commit() is often necessary


class TestModule(object):
    def test_authname_parts__op_username_simple__correctly_parsed(self):
        (namespace, username) = module.authname_parts("op=userfoo")

        nose.tools.assert_equal(namespace, "op")
        nose.tools.assert_equal(username, "userfoo")

    def test_authname_parts__op_username_quoted__correctly_parsed(self):
        (namespace, username) = module.authname_parts("op=user%40example.com")

        nose.tools.assert_equal(namespace, "op")
        nose.tools.assert_equal(username, "user@example.com")

    def test_authpass_parts__raw_password_simple__correctly_parsed(self):
        (passtype, password) = module.authpass_parts("raw=secret123")

        nose.tools.assert_equal(passtype, "raw")
        nose.tools.assert_equal(password, "secret123")

    def test_authpass_parts__raw_password_quoted__correctly_parsed(self):
        (passtype, password) = module.authpass_parts("raw=supersecret%21")

        nose.tools.assert_equal(passtype, "raw")
        nose.tools.assert_equal(password, "supersecret!")


class TestPaymentsView(za.test.biz.FakeServiceFixture):
    def inner_setup(self):
        self._app = flask.Flask(__name__)
        self._client = self._app.test_client()
        self._app.register_blueprint(module.create_blueprint(""))
        self._app.config["SERVER_NAME"] = "test"

    def do_setup(self):
        self.user = biz.accounts.User(
            username="some-user",
            locale="en_ke",
            raw_password=u"some-user")

        biz.g.session.add(self.user)
        biz.commit()

        with self._app.app_context():
            self._url = flask.url_for("biz_api.payments")

    def test_post__authorized_actor__200_returned(self):
        self.do_setup()

        payment_data = za.util.jsonify({
            "phone": "+15551234567",
            "amount": 10
        })

        headers = {}
        headers["Authorization"] = "Basic {}".format(
            base64.b64encode("op={}:raw={}".format(
                self.user.username, self.user.username)))

        response = self._client.post(
            self._url,
            data=payment_data,
            headers=headers,
            content_type="application/json")

        nose.tools.assert_equal(response.status, '200 OK')


class TestUserView(za.test.biz.FakeServiceFixture):
    def inner_setup(self, all_groups=False):
        self._app = flask.Flask(__name__)
        self._client = self._app.test_client()
        self._app.register_blueprint(module.create_blueprint(""))
        self._app.config["SERVER_NAME"] = "test"

    def do_setup(self, all_groups=False):
        self.user = biz.accounts.User(
            username="justin",
            locale="en_KE",
            raw_password=u"justin")

        biz.g.session.add(self.user)
        biz.commit()

        with self._app.app_context():
            self._url = flask.url_for("biz_api.user", id_=self.user.id)

    def test_get__user_media_returned(self):
        self.do_setup()

        response = self._client.get(self._url)
        media = za.util.dejsonify(response.data)

        nose.tools.assert_equal(media["username"], 'justin')

    def test_patch__new_last_name__user_media_returned(self):
        self.do_setup()

        patch_data = za.util.jsonify({
            "last_name": "new"})

        response = self._client.patch(
            self._url,
            data=patch_data,
            content_type="application/json")

        media = za.util.dejsonify(response.data)

        nose.tools.assert_equal(media["last_name"], 'new')

    def test_delete__no_content_response(self):
        self.do_setup()

        response = self._client.delete(
            self._url,
            content_type="application/json")

        nose.tools.assert_equal(response.status, '204 NO CONTENT')
