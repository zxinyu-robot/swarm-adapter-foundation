"""Go2 端 StreamVLN 客户端 — 订阅 RGB + 里程计，HTTP 上行推理，解析动作执行。

部署在 Go2 (ROS2 Foxy)，需安装 unitree_ros2 相关 msg。
"""
import io
import json
import math
import sys
import threading
import time

import numpy as np
import PIL.Image as PIL_Image
import rclpy
import requests
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool
from unitree_api.msg import Request, RequestHeader
from unitree_go.msg import SportModeState

from pid_controller import PID_controller
from utils import ReadWriteLock

# ============ 配置（按你的环境改）============
SERVER_URL = "http://192.0.2.100:5801/eval_vln"  # x86 服务端 IP
INSTRUCTION = "Walk forward and stop when you exit the room."
RGB_TOPIC = "/camera/camera/color/image_raw"  # 你的 RGB topic
ODOM_TOPIC = "/sportmodestate"
# =============================================

policy_init = True
pid = PID_controller(Kp_trans=3.0, Kd_trans=0.5, Kp_yaw=3.0, Kd_yaw=0.5, max_v=1.0, max_w=1.2)
manager = None

rgb_rw_lock = ReadWriteLock()
odom_rw_lock = ReadWriteLock()


def eval_vln(image, instruction, url=SERVER_URL):
    """上行 RGB JPEG + 指令，获取动作序列。"""
    global policy_init

    pil = PIL_Image.fromarray(image)
    buf = io.BytesIO()
    pil.save(buf, format="jpeg", quality=85)
    buf.seek(0)

    payload = {
        "reset": policy_init,
        "instruction": instruction,
    }
    policy_init = False

    t0 = time.time()
    resp = requests.post(
        url,
        files={"image": ("rgb.jpg", buf, "image/jpeg")},
        data={"json": json.dumps(payload)},
        timeout=150,
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"[vln] latency={time.time() - t0:.2f}s action={result.get('action')}")
    return result.get("action", [0])


def control_thread():
    while True:
        homo_odom = manager.homo_odom.copy() if manager.homo_odom is not None else None
        vel = manager.vel.copy() if manager.vel is not None else None
        homo_goal = manager.homo_goal.copy() if manager.homo_goal is not None else None

        if homo_odom is not None and vel is not None and homo_goal is not None:
            v, w, e_p, e_r = pid.solve(homo_odom, homo_goal, vel)
            manager.move(v, 0, w)
            if abs(e_p) < 0.1 and abs(e_r) < 0.1:
                manager.trigger_replan()

        time.sleep(0.1)


def planning_thread():
    while True:
        if not manager.should_plan:
            time.sleep(0.05)
            continue

        rgb_rw_lock.acquire_read()
        rgb_image = manager.rgb_image
        rgb_rw_lock.release_read()

        if rgb_image is None:
            time.sleep(0.05)
            continue

        actions = eval_vln(rgb_image, INSTRUCTION)

        odom_rw_lock.acquire_write()
        manager.should_plan = False
        manager.request_cnt += 1
        manager.incremental_change_goal(actions)
        odom_rw_lock.release_write()


class Go2VlnManager(Node):
    def __init__(self):
        super().__init__("go2_vln_client")
        self.rgb_sub = self.create_subscription(Image, RGB_TOPIC, self.rgb_callback, 1)
        self.odom_sub = self.create_subscription(SportModeState, ODOM_TOPIC, self.odom_callback, 10)
        self.control_pub = self.create_publisher(Request, "/api/sport/request", 5)

        self.cv_bridge = CvBridge()
        self.rgb_image = None
        self.homo_goal = None
        self.homo_odom = None
        self.vel = None
        self.request_cnt = 0
        self.odom_cnt = 0
        self.should_plan = True  # 启动即请求首次规划

    def rgb_callback(self, msg):
        rgb_rw_lock.acquire_write()
        self.rgb_image = self.cv_bridge.imgmsg_to_cv2(msg, "bgr8")
        rgb_rw_lock.release_write()

    def odom_callback(self, msg):
        downsample = 5
        self.odom_cnt += 1
        if self.odom_cnt % downsample != 0:
            return

        odom_rw_lock.acquire_write()
        yaw = msg.imu_state.rpy[2]
        r0 = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
        self.homo_odom = np.eye(4)
        self.homo_odom[:2, :2] = r0
        self.homo_odom[:2, 3] = [msg.position[0], msg.position[1]]
        self.vel = [msg.velocity[0], msg.yaw_speed]

        if self.odom_cnt == downsample:
            self.homo_goal = self.homo_odom.copy()
        odom_rw_lock.release_write()

    def trigger_replan(self):
        self.should_plan = True

    def incremental_change_goal(self, actions):
        if self.homo_goal is None:
            return
        homo_goal = self.homo_goal.copy()

        for act in actions:
            if act == 0:
                pass
            elif act == 1:  # 前进 25cm
                yaw = math.atan2(homo_goal[1, 0], homo_goal[0, 0])
                homo_goal[0, 3] += 0.25 * np.cos(yaw)
                homo_goal[1, 3] += 0.25 * np.sin(yaw)
            elif act == 2:  # 左转 15°
                angle = math.radians(15)
                rot = np.array([
                    [math.cos(angle), -math.sin(angle), 0],
                    [math.sin(angle), math.cos(angle), 0],
                    [0, 0, 1],
                ])
                homo_goal[:3, :3] = rot @ homo_goal[:3, :3]
            elif act == 3:  # 右转 15°
                angle = math.radians(-15)
                rot = np.array([
                    [math.cos(angle), -math.sin(angle), 0],
                    [math.sin(angle), math.cos(angle), 0],
                    [0, 0, 1],
                ])
                homo_goal[:3, :3] = rot @ homo_goal[:3, :3]

        self.homo_goal = homo_goal

    def move(self, vx, vy, vyaw):
        req = Request()
        req.header = RequestHeader()
        req.header.identity._api_id = 1008  # SPORT_API_ID_MOVE
        req.header.identity.id = time.monotonic_ns()
        req.parameter = json.dumps({"x": vx, "y": vy, "z": vyaw})
        self.control_pub.publish(req)


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        SERVER_URL = sys.argv[1]
    if len(sys.argv) >= 3:
        INSTRUCTION = sys.argv[2]

    rclpy.init()
    manager = Go2VlnManager()

    threading.Thread(target=control_thread, daemon=True).start()
    threading.Thread(target=planning_thread, daemon=True).start()

    print(f"Go2 VLN client -> {SERVER_URL}")
    print(f"Instruction: {INSTRUCTION}")

    try:
        rclpy.spin(manager)
    except KeyboardInterrupt:
        pass
    finally:
        manager.destroy_node()
        rclpy.shutdown()
