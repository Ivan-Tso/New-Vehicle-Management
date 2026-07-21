# 公务车管理系统 - 管理员功能部署说明

## 主要更新

### 1. 管理员/用户双角色系统
- **管理员 (admin)**: 可以编辑所有记录、管理用户账号
- **普通用户 (user)**: 只能查看和新增记录，不能编辑

### 2. 默认账号
| 用户名 | 密码 | 角色 | 权限 |
|--------|------|------|------|
| admin | Admin@123 | 管理员 | 全部权限（编辑记录 + 用户管理） |
| user | User@123 | 普通用户 | 只能查看和新增 |

### 3. 管理员专属功能
- ✅ 编辑所有车辆、行驶记录、费用记录
- ✅ 添加/编辑/删除用户账号
- ✅ 分配用户角色（管理员/普通用户）
- ✅ 重置用户密码

### 4. 登录页面更新
- 需要输入用户名和密码
- 显示当前用户和角色
- 管理员在侧边栏看到"管理员"菜单

---

## PythonAnywhere 部署步骤

### 第一步：上传更新后的文件

上传以下文件到 PythonAnywhere：
- `app.py` (更新版)
- `translations.py` (更新版)
- `templates/login.html` (更新版)
- `templates/base.html` (更新版)
- `templates/vehicles.html` (更新版)
- `templates/usage_list.html` (更新版)
- `templates/expense_list.html` (更新版)
- `templates/admin_users.html` (新增)
- `templates/admin_user_form.html` (新增)

### 第二步：初始化数据库

在 PythonAnywhere 的 Bash 终端执行：

```bash
cd vehicle-management
python3 -c "
from app import app, init_db
with app.app_context():
    init_db()
    print('数据库初始化完成')
"
```

### 第三步：重新加载 Web 应用

1. 登录 PythonAnywhere Dashboard
2. 点击 "Web" 标签
3. 点击绿色的 "Reload" 按钮

### 第四步：测试登录

1. 访问：`https://你的用户名.pythonanywhere.com`
2. 用 admin/Admin@123 登录
3. 验证侧边栏是否显示 "管理员" 菜单
4. 点击进入 "用户管理" 页面

---

## 用户管理操作指南

### 添加新用户
1. 用 admin 账号登录
2. 点击侧边栏 "管理员" → "用户管理"
3. 点击 "添加用户"
4. 填写用户名、密码、选择角色
5. 保存

### 修改用户密码
1. 进入用户管理页面
2. 点击要修改用户旁边的 "编辑"
3. 输入新密码（用户名为灰色不可修改）
4. 保存

### 删除用户
1. 进入用户管理页面
2. 点击要删除用户旁边的 "删除" 按钮
3. 确认删除
4. 注意：不能删除自己

---

## 安全建议

1. **首次登录后立即修改默认密码**
   - admin 账号密码必须修改
   - 可用中文密码

2. **定期备份数据库**
   - 在 PythonAnywhere 下载 vehicle.db
   - 或导出 CSV 备份

3. **限制用户数量**
   - 只给必要人员分配账号
   - 普通员工使用 user 角色

4. **监控登录日志**
   - 如发现异常及时修改密码

---

## 故障排除

### 问题：登录后看不到"管理员"菜单
- 确认使用 admin 账号登录
- 检查 session 是否正常（清除浏览器缓存）

### 问题：用户管理页面 404
- 确认 app.py 已上传最新版本
- 在 PythonAnywhere 重新加载 Web 应用

### 问题：无法编辑记录
- 确认使用 admin 账号
- user 角色只能查看和新增

### 问题：数据库表不存在
- 在 PythonAnywhere 执行 init_db()
- 检查 wsgi.py 是否正确配置

---

## 电脑端管理员特殊说明

对于公司电脑端管理员：
1. 使用 admin 账号登录
2. 可以编辑所有记录
3. 可以管理其他用户账号
4. 建议定期备份数据

对于普通用户：
1. 使用 user 或其他用户账号登录
2. 可以查看和新增记录
3. 不能编辑已有记录
4. 不能访问用户管理功能
