import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import time

from cw.actions_review import CWActionReview
from cw.actions_runner import CWActionRunner
from cw.actions_store import CWActionStore
from cw.agent import CWAgent
from cw.agent_tools import CWAgentTools
from cw.apps import CWApps
from cw.config import CWConfig
from cw.device_client import CWDeviceClient
from cw.guard import CWGuard
from cw.journal import CWJournal
from cw.llm_client import CWLLMClient
from cw.mock_device import CWMockDevice
from cw.ops import CWOperator
from cw.protocol import CWErrorCode, CWProtocolError
from cw.relay import CWRelay
from cw.session import CWSession
from cw.web import CWWeb


class CWServer:
    def __init__(self, config=None, force_mock=False):
        self.config = config or CWConfig()
        self.config.ensure_dirs()
        self.journal = CWJournal(self.config)
        self.session = CWSession(self.config, self.journal)
        self.device = self._make_device(force_mock)
        self.guard = CWGuard(self.config)
        self.operator = CWOperator(self.config, self.device, self.guard, self.journal, self.session)
        self.reviewer = CWActionReview(self.config)
        self.store = CWActionStore(self.config, self.reviewer)
        self.runner = CWActionRunner(self.config, self.operator, self.journal, self.store)
        self.operator.set_action_runner(self.runner)
        self.apps = CWApps(self.config)
        self.apps.load()
        self.tools = CWAgentTools(self.config, self.operator, self.store, self.session,
                                  self.journal, self.apps)
        self.llm = CWLLMClient(self.config)
        self.agent = CWAgent(self.config, self.operator, self.tools, self.store, self.llm,
                             self.journal, self.session, self.apps)
        self.runner.asker = self.agent._ask
        self.relay = CWRelay(self.config, self.journal)
        self.relay.on_stop = lambda: self.agent.stop("app_button")
        self.journal.add_listener(self.relay.broadcast_op)
        self.web = CWWeb(self.config, self.session, self.operator, self.agent, self.store,
                         self.relay, self.journal, self.device)

    def _make_device(self, force_mock):
        if force_mock or self.config.mock:
            return CWMockDevice(self.config)
        client = CWDeviceClient(self.config.device_ip, self.config.device_port,
                                self.config.token, self.config.device_timeout)
        try:
            client.ping()
            client.device_info(refresh=True)
            client.ensure_session()
            return client
        except CWProtocolError as exc:
            print("⚠️ 设备不可达（%s），切换到 mock 设备" % exc.message)
            try:
                client.close()
            except Exception:
                pass
            return CWMockDevice(self.config)

    def start(self):
        self.relay.start()
        self.web.start()
        info = {}
        try:
            info = self.device.device_info(refresh=True)
        except Exception:
            pass
        screen = info.get("screen") or {}
        print("🐾 CatPaws 已启动")
        print("🌐 控制台      %s" % self.web.url())
        print("📺 视频中继    ws://%s:%d/ws" % (self.config.relay_host, self.config.relay_port))
        print("📱 设备        %s:%d%s" % (self.config.device_ip, self.config.device_port,
                                          "（mock）" if isinstance(self.device, CWMockDevice) else ""))
        if screen:
            print("🖥️  屏幕        %sx%s @ scale %s" % (tuple(screen.get("pixel", [0, 0]))
                                                        + (screen.get("scale"),)))
        print("🛑 停止词      在页面点停止，或 POST /cw/stop")

    def stop(self):
        try:
            self.agent.stop("shutdown")
        except Exception:
            pass
        self.web.stop()
        self.relay.stop()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = list(argv if argv is not None else sys.argv[1:])
    force_mock = "--mock" in args
    server = CWServer(force_mock=force_mock)
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 CatPaws 已退出")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
