class CredentialsManager:
    """
    讯飞API凭据管理器，用于在不同模块间共享API凭据
    """
    _instance = None
    app_id = None
    api_key = None
    api_secret = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CredentialsManager, cls).__new__(cls)
        return cls._instance

    def set_credentials(self, app_id: str, api_key: str, api_secret: str):
        """
        设置讯飞API的认证凭据
        :param app_id: 应用ID
        :param api_key: API密钥
        :param api_secret: API密钥密钥
        """
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret

    def get_credentials(self):
        """
        获取讯飞API的认证凭据
        :return: (app_id, api_key, api_secret) 元组
        """
        return self.app_id, self.api_key, self.api_secret

    def is_configured(self):
        """
        检查凭据是否已配置
        :return: bool
        """
        return self.app_id is not None and self.api_key is not None and self.api_secret is not None


# 创建全局实例
credentials_manager = CredentialsManager()