from obswebsocket import obsws, events, requests
from enum import Enum
from func.log.default_log import DefaultLog

class VideoControl(Enum):
    RESTART = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
    STOP = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
    PAUSE = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
    PLAY = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
    NEXT = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_NEXT"
    PREVIOUS = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PREVIOUS"

class VideoStatus(Enum):
    STOP = "OBS_MEDIA_STATE_STOPPED"
    PAUSE = "OBS_MEDIA_STATE_PAUSED"
    PLAY = "OBS_MEDIA_STATE_PLAYING"
    END = "OBS_MEDIA_STATE_ENDED"

class ObsWebSocket:
      # 设置控制台日志
      log = DefaultLog().getLogger()

      def __init__(self,host,port,password,switch):
          self.host = host
          self.port = port
          self.password = password
          self.switch = switch
          self.ws = None
          if switch == True:
              self.ws = obsws(self.host, self.port, self.password)
          else:
              self.log.debug(f"OBS直播控制未启用")
      
      def connect(self):
          if self.switch == True and self.ws is not None:
              try:
                  self.ws.connect()
                  self.log.info("OBS WebSocket 连接成功")
              except Exception as e:
                  self.log.error(f"OBS WebSocket 连接失败: {e}")
                  raise  # 可选择抛出，让上层处理；或者设置标志后不抛出
            
      def disconnect(self):
          if self.switch == True:
             self.ws.disconnect()
    
      #影片输出
      def play_video(self,inputName,file_path):
          if self.switch == False:
              return
          return self.ws.call(requests.SetInputSettings(inputName=inputName,inputSettings={"local_file": file_path}))
      
      #影片控制
      def control_video(self,inputName,videoStatus):
          if self.switch == False:
              return
          return self.ws.call(requests.TriggerMediaInputAction(inputName=inputName,mediaAction=videoStatus))

      #获取影片播放状态
      def get_video_status(self,inputName):
          if self.switch == False:
              return
          data = self.ws.call(requests.GetMediaInputStatus(inputName=inputName))
          return data.datain["mediaState"]

      #场景切换
      def change_scene(self,sceneName):
          if self.switch == False:
              return
          return self.ws.call(requests.SetCurrentProgramScene(sceneName=sceneName))
      
      #图片输出
      def show_image(self,inputName,file_path):
          if self.switch == False:
              return
          return self.ws.call(requests.SetInputSettings(inputName=inputName,inputSettings={"file": file_path}))
      
      #文字输出
      def show_text(self,inputName,text):
          if self.switch == False:
              return
          return self.ws.call(requests.SetInputSettings(inputName=inputName, inputSettings={"text": text}))

