import yaml

class ConfigBase:
      def __init__(self,filename,encoding):
          with open(filename, "r", encoding = encoding) as f:
              cont = f.read()
          self.config = yaml.load(cont, Loader=yaml.FullLoader)

      def get_config(self):
          return self.config
