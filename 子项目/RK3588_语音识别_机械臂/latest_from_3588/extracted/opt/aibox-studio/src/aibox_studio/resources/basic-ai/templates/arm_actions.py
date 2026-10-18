from aibox import Arm

arm = Arm()
arm.pose("直立")
arm.open()
arm.half_open()
arm.close()
arm.action("抓取")
print("机械臂动作体验完成")
