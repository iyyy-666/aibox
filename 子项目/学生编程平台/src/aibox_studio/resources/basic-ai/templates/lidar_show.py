from aibox import Lidar

lidar = Lidar()
lidar.show()
distance = lidar.get_distance()
print("检测距离：", distance, "毫米")
