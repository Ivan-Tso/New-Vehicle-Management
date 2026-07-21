# ☁️ PythonAnywhere 部署步骤（手把手）

> 目标：把公务车管理系统部署到PythonAnywhere，公司电脑和手机都能通过浏览器访问
> 预计时间：15-20分钟
> 费用：免费

═════════════════════════════════════════════
## 第一步：注册 PythonAnywhere 账号

1. 手机或电脑打开 https://www.pythonanywhere.com
2. 点击 "Create a free account"
3. 填写：
   - Username: 选一个你记得住的名字（如 usdaclerk）
   - Email: 你的邮箱
   - Password: 设一个密码
4. 验证邮箱（查收邮件，点验证链接）
5. 登录后，你看到的页面就是PythonAnywhere的Dashboard

⚠️ 注意：免费账号用户名会出现在网址中
   你的系统地址将是: https://usdaclerk.pythonanywhere.com

═════════════════════════════════════════════
## 第二步：上传项目文件

### 方法A：网页上传（最简单）

1. 在Dashboard点 "Files" 标签
2. 进入 /home/usdaclerk/ 目录
3. 点 "New directory" 创建文件夹 vehicle-management
4. 进入 vehicle-management 文件夹
5. 逐个上传以下文件：

   必须文件清单：
   ┌─────────────────────────┬──────────────┐
   │ 文件                     │ 说明          │
   ├─────────────────────────┼──────────────┤
   │ app.py                  │ 主程序        │
   │ requirements.txt        │ 依赖清单      │
   │ .secret_key             │ Session密钥   │
   └─────────────────────────┴──────────────┘

   然后创建子目录并上传：
   - templates/ 文件夹 → 上传所有 .html 文件
   - static/ 文件夹 → 上传 manifest.json, icon.svg, icon-192.png, icon-512.png

### 方法B：用git（如果你会的话，更快）

1. 先把项目推到GitHub
2. 在PythonAnywhere的Console里执行：
   git clone https://github.com/你的用户名/vehicle-management.git

═════════════════════════════════════════════
## 第三步：安装Python依赖

1. 在Dashboard点 "$ Bash" 打开终端
2. 执行：

   cd vehicle-management
   pip install --user -r requirements.txt

3. 等待安装完成（约30秒）
4. 看到 "Successfully installed flask waitress" 就对了

═════════════════════════════════════════════
## 第四步：初始化数据库

在同一个Bash终端里执行：

   cd vehicle-management
   python3 -c "
   from app import app, init_db
   with app.app_context():
       init_db()
   print('数据库初始化完成')
   "

看到 "数据库初始化完成" 即成功。

═════════════════════════════════════════════
## 第五步：配置Web应用（最关键！）

1. 在Dashboard点 "Web" 标签
2. 点 "Add a new web app"
3. 选择域名: usdaclerk.pythonanywhere.com（免费版）
4. 选择Python版本: Python 3.10（或最新的3.x）
5. 选择框架: Manual configuration（手动配置）
6. 点Next完成创建

7. 在Web配置页面，找到以下项目并填写：

   ┌────────────────┬──────────────────────────────────────────────────┐
   │ 配置项          │ 填写内容                                         │
   ├────────────────┼──────────────────────────────────────────────────┤
   │ Source code     │ /home/usdaclerk/vehicle-management               │
   │ Working dir     │ /home/usdaclerk/vehicle-management               │
   │ WSGI file       │ /home/usdaclerk/vehicle-management/wsgi.py       │
   │ Python version  │ Python 3.10                                      │
   │ Virtualenv      │ 留空（免费版不需要）                                │
   └────────────────┴──────────────────────────────────────────────────┘

8. 点击 WSGI file 旁边的链接，编辑 wsgi.py，替换为以下内容：

```python
import sys
import os

# 项目目录
project_dir = '/home/usdaclerk/vehicle-management'
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

os.chdir(project_dir)

from app import application as app  # noqa: E402
```

9. 保存 wsgi.py

10. 回到Web页面，点绿色的 "Reload" 按钮

═════════════════════════════════════════════
## 第六步：访问测试

1. 打开浏览器，访问：
   https://usdaclerk.pythonanywhere.com

2. 你应该看到登录页面
3. 输入密码: usda2024
4. 登录成功！手机端入口:
   https://usdaclerk.pythonanywhere.com/mobile

═════════════════════════════════════════════
## 第七步：修改默认密码（重要！）

1. 在Bash终端执行：
   python3 -c "
   import hashlib
   new_password = '你的新密码'
   print('新密码的hash值:')
   print(hashlib.sha256(new_password.encode()).hexdigest())
   "

2. 复制输出的hash值
3. 编辑 app.py，找到这一行：
   AUTH_PASSWORD_HASH = hashlib.sha256('usda2024'.encode()).hexdigest()
4. 替换为：
   AUTH_PASSWORD_HASH = '你刚才复制的hash值'
5. 保存，然后在Web页面点Reload

═════════════════════════════════════════════
## 手机端设置

### 添加到手机主屏幕（像App一样用）

iPhone:
1. 用Safari打开 https://usdaclerk.pythonanywhere.com/mobile
2. 点底部分享按钮 (方框+向上箭头)
3. 滑动找到 "添加到主屏幕"
4. 点"添加"

Android:
1. 用Chrome打开上面的地址
2. 点右上角三个点菜单
3. 选 "添加到主屏幕" 或 "安装应用"

═════════════════════════════════════════════
## 免费版限制

| 项目 | 限制 | 对我们的影响 |
|------|------|-------------|
| CPU | 每天100秒 | 日常录入够用，大型报表可能超 |
| 磁盘 | 512MB | SQLite数据库足够 |
| 流量 | 每月有限 | 日常使用没问题 |
| 定时任务 | 每天1个 | 可用于自动备份 |

如果将来觉得不够用，可升级到Hacker计划（$5/月），限制大幅放宽。

═════════════════════════════════════════════
## 常见问题

Q: 页面报500错误？
A: 点Web页面的 "Log files" 查看错误日志，通常是路径写错或依赖没装。

Q: 公司电脑访问不了？
A: PythonAnywhere是国内可访问的。如果公司有白名单限制，
   可能需要IT部门放行 *.pythonanywhere.com 域名。

Q: 数据会丢吗？
A: PythonAnywhere的免费版磁盘是持久的，数据库文件不会丢。
   但建议定期导出CSV备份。

Q: 每天CPU 100秒够不够？
A: 每次页面访问大约用0.1-0.5秒CPU时间。
   100秒 ≈ 每天200-1000次页面访问，日常使用足够。
