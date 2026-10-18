from aibox import Arm

arm = Arm()
arm.pose("直立")
arm.open()
arm.action("抓取")
print("三个动作执行完成")
