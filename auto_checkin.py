import os
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from loguru import logger
from pydantic import BaseModel, Field

# 假设 ext_notification 模块已实现
from ext_notification import send_notification


class Response(BaseModel):
    code: int = Field(..., alias="code", description="返回值")
    msg: str = Field(..., alias="msg", description="提示信息")
    success: Optional[bool] = Field(None, alias="success", description="token有时才有")
    data: Optional[Any] = Field(None, alias="data", description="请求成功才有")


class KurobbsClientException(Exception):
    """Custom exception for Kurobbs client errors."""
    pass


class KurobbsClient:
    FIND_ROLE_LIST_API_URL = "https://api.kurobbs.com/gamer/role/default"
    SIGN_URL = "https://api.kurobbs.com/encourage/signIn/v2"
    USER_SIGN_URL = "https://api.kurobbs.com/user/signIn"
    USER_MINE_URL = "https://api.kurobbs.com/user/mineV2"

    def __init__(self, token: str, account_name: str = "未命名账号"):
        self.token = token
        self.account_name = account_name  # 添加账号标识
        self.result: Dict[str, str] = {}
        self.exceptions: List[Exception] = []

    def get_headers(self) -> Dict[str, str]:
        """Get the headers required for API requests."""
        return {
            "osversion": "Android",
            "devcode": "2fba3859fe9bfe9099f2696b8648c2c6",
            "countrycode": "CN",
            "ip": "10.0.2.233",
            "model": "2211133C",
            "source": "android",
            "lang": "zh-Hans",
            "version": "1.0.9",
            "versioncode": "1090",
            "token": self.token,
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/3.10.0",
        }

    def make_request(self, url: str, data: Dict[str, Any]) -> Response:
        """Make a POST request to the specified URL with the given data."""
        headers = self.get_headers()
        response = requests.post(url, headers=headers, data=data)
        try:
            res = Response.model_validate_json(response.content)
            logger.debug(f"[{self.account_name}] 响应: {res.model_dump_json(indent=2, exclude={'data'})}")
            return res
        except Exception as e:
            logger.error(f"[{self.account_name}] 解析响应失败: {str(e)}")
            raise KurobbsClientException(f"[{self.account_name}] API响应解析失败: {str(e)}") from e

    def get_mine_info(self, type: int = 1):
        """Get mine info"""
        data = {"type": type}
        res = self.make_request(self.USER_MINE_URL, data)
        return res.data

    def get_user_game_list(self, user_id: int) -> Dict[str, Any]:
        """Get the list of games for the user."""
        data = {"queryUserId": user_id}
        res = self.make_request(self.FIND_ROLE_LIST_API_URL, data)
        return res.data

    def checkin(self) -> Response:
        """Perform the check-in operation."""
        try:
            mine_info = self.get_mine_info()
            if not mine_info or "mine" not in mine_info or "userId" not in mine_info["mine"]:
                raise KurobbsClientException(f"[{self.account_name}] 无法获取用户ID")
                
            user_id = mine_info["mine"]["userId"]
            user_game_list = self.get_user_game_list(user_id=user_id)
            
            # 获取北京时间（UTC+8）
            beijing_tz = ZoneInfo('Asia/Shanghai')
            beijing_time = datetime.now(beijing_tz)

            # 检查是否有角色信息
            if not user_game_list or "defaultRoleList" not in user_game_list or not user_game_list["defaultRoleList"]:
                raise KurobbsClientException(f"[{self.account_name}] 未找到角色信息")
            
            role_info = user_game_list["defaultRoleList"][0]

            data = {
                "gameId": role_info.get("gameId", 2),
                "serverId": role_info.get("serverId", None),
                "roleId": role_info.get("roleId", 0),
                "userId": role_info.get("userId", 0),
                "reqMonth": f"{beijing_time.month:02d}",
            }
            return self.make_request(self.SIGN_URL, data)
        except Exception as e:
            # 添加账号标识到异常信息
            raise KurobbsClientException(f"[{self.account_name}] 签到奖励签到失败: {str(e)}") from e

    def sign_in(self) -> Response:
        """Perform the sign-in operation."""
        try:
            return self.make_request(self.USER_SIGN_URL, {"gameId": 2})
        except Exception as e:
            # 添加账号标识到异常信息
            raise KurobbsClientException(f"[{self.account_name}] 社区签到失败: {str(e)}") from e

    def _process_sign_action(
            self,
            action_name: str,
            action_method: Callable[[], Response],
            success_message: str,
            failure_message: str,
    ):
        """
        Handle the common logic for sign-in actions.

        :param action_name: The name of the action (used to store the result).
        :param action_method: The method to call for the sign-in action.
        :param success_message: The message to log on success.
        :param failure_message: The message to log on failure.
        """
        try:
            resp = action_method()
            if resp.success:
                self.result[action_name] = f"[{self.account_name}] {success_message}"
            else:
                self.exceptions.append(KurobbsClientException(f"[{self.account_name}] {failure_message}: {resp.msg}"))
        except KurobbsClientException as e:
            self.exceptions.append(e)

    def start(self):
        """Start the sign-in process."""
        logger.info(f"开始处理账号: {self.account_name}")
        
        self._process_sign_action(
            action_name="checkin",
            action_method=self.checkin,
            success_message="签到奖励签到成功",
            failure_message="签到奖励签到失败",
        )

        self._process_sign_action(
            action_name="sign_in",
            action_method=self.sign_in,
            success_message="社区签到成功",
            failure_message="社区签到失败",
        )

        self._log()

    @property
    def msg(self):
        return ", ".join(self.result.values()) + "!" if self.result else ""

    def _log(self):
        """Log the results and raise exceptions if any."""
        if msg := self.msg:
            logger.success(msg)
        if self.exceptions:
            # 记录错误但不中断程序
            for e in self.exceptions:
                logger.error(str(e))


def configure_logger(debug: bool = False):
    """Configure the logger based on the debug mode."""
    logger.remove()  # Remove default logger configuration
    log_level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stdout, 
        level=log_level, 
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>"
    )


def main():
    """Main function to handle command-line arguments and start the sign-in process."""
    # 从环境变量获取多个TOKEN，支持分号分隔
    tokens_str = os.getenv("TOKENS", "")
    account_names_str = os.getenv("ACCOUNT_NAMES", "")
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    configure_logger(debug)
    
    # 解析TOKEN列表
    tokens = []
    if tokens_str:
        tokens = tokens_str.split(';')
    
    # 解析账号名称列表
    account_names = []
    if account_names_str:
        account_names = account_names_str.split(';')
    
    # 确保账号名称与TOKEN数量匹配
    if account_names and len(account_names) != len(tokens):
        logger.warning("账号名称数量与TOKEN数量不匹配，将使用默认账号名称")
        account_names = []
    
    # 如果没有账号名称，生成默认名称
    if not account_names:
        account_names = [f"账号{i+1}" for i in range(len(tokens))]
    
    all_results = []
    all_errors = []
    
    # 遍历所有TOKEN
    for i, token in enumerate(tokens):
        token = token.strip()
        if not token:
            continue
            
        account_name = account_names[i]
        try:
            logger.info(f"处理账号 {i+1}/{len(tokens)}: {account_name}")
            kurobbs = KurobbsClient(token, account_name)
            kurobbs.start()
            
            if kurobbs.msg:
                all_results.append(kurobbs.msg)
            
            # 收集错误信息
            if kurobbs.exceptions:
                all_errors.extend([str(e) for e in kurobbs.exceptions])
                
        except Exception as e:
            logger.exception(f"[{account_name}] 处理过程中发生未捕获的异常")
            all_errors.append(f"[{account_name}] 处理失败: {str(e)}")
    
    # 汇总结果并发送通知
    final_message = ""
    
    if all_results:
        final_message += "🎉 签到成功:\n" + "\n".join(all_results) + "\n\n"
    
    if all_errors:
        final_message += "❌ 遇到错误:\n" + "\n".join(all_errors)
    
    if not final_message:
        final_message = "没有需要处理的账号"
    
    # 发送通知
    logger.info("所有账号处理完成")
    logger.info(final_message)
    send_notification(final_message)
    
    # 如果有错误则退出状态码为1
    if all_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
