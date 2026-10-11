from aibox import Arm

arm = Arm()
arm.servo(1, 1500)
arm.adjust(1, 30)
print("1号舵机微调完成")
