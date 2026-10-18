from aibox import Arm, Voice

command = Voice().listen()
Arm().command(command)
print("执行语音指令：", command)
