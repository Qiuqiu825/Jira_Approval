from flask import Flask, render_template, request, jsonify, session
import os
from dotenv import load_dotenv
import urllib3
import json
import requests
import re

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')  # 从环境变量读取密钥，生产请设置为安全值

def get_jira_client():
    """获取Jira客户端"""
    load_dotenv()
    server = os.getenv('JIRA_SERVER')
    email = os.getenv('JIRA_USER')
    api_token = os.getenv('JIRA_API_TOKEN')

    try:
        # 使用Personal Access Token进行认证
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Accept': 'application/json'
        }
        session = requests.Session()
        session.headers.update(headers)
        session.verify = False
        
        # 测试连接
        response = session.get(f"{server}/rest/api/2/myself")
        if response.status_code == 200:
            return session
        else:
            return None
    except Exception as e:
        return None

def extract_issue_key(link):
    """从Jira链接中提取issue key"""
    issue_key = None
    
    # 处理第一种和第二种格式: casement.scredit.io URLs with jiraKey parameter
    if 'jiraKey=' in link:
        parts = link.split('jiraKey=')
        if len(parts) > 1:
            issue_key = parts[1].split('&')[0].strip()
    
    # 处理第三种格式: jira.shopee.io/browse/SPSK-216547
    elif 'browse/' in link:
        parts = link.split('browse/')
        if len(parts) > 1:
            issue_key = parts[1].split('?')[0].strip()
    
    # 如果以上方法都没提取到，且输入像是直接的ticket号
    elif '-' in link and not link.startswith('http'):
        issue_key = link.strip()
    
    if issue_key:
        # 清理issue key，确保格式正确
        issue_key = issue_key.split('?')[0].strip()
        if issue_key.startswith('https://'):
            issue_key = issue_key.split('/')[-1]
    
    return issue_key

def get_issue_info(session, issue_key):
    """获取Jira ticket信息"""
    load_dotenv()
    server = os.getenv('JIRA_SERVER')
    
    try:
        url = f"{server}/rest/api/2/issue/{issue_key}"
        response = session.get(url)
        
        if response.status_code == 200:
            data = response.json()
            # 正确处理Financial Risk字段
            financial_risk = data['fields'].get('customfield_14501', {})
            if isinstance(financial_risk, dict) and 'value' in financial_risk:
                financial_risk = financial_risk['value']
            else:
                financial_risk = '未设置'
                
            return {
                'key': data['key'],
                'title': data['fields']['summary'],
                'reporter': data['fields']['reporter']['displayName'],
                'financial_risk': financial_risk,
                'status': data['fields']['status']['name'],
                'link': f"{server}/browse/{data['key']}"
            }
        else:
            return None
            
    except Exception as e:
        return None

def get_issue_description(session, issue_key):
    """获取Jira ticket的描述信息"""
    load_dotenv()
    server = os.getenv('JIRA_SERVER')
    
    try:
        url = f"{server}/rest/api/2/issue/{issue_key}"
        response = session.get(url)
        
        if response.status_code == 200:
            data = response.json()
            description = data['fields'].get('description', '未设置')
            return description
        else:
            return None
            
    except Exception as e:
        return None

def approve_issue(session, issue_key, risk_url=""):
    """在Jira中签核ticket"""
    load_dotenv()
    server = os.getenv('JIRA_SERVER')
    
    try:
        # 获取当前issue的信息
        url = f"{server}/rest/api/2/issue/{issue_key}"
        response = session.get(url)
        if response.status_code != 200:
            return False, f"无法获取ticket信息: HTTP {response.status_code}"
            
        issue_data = response.json()
        issue_id = issue_data['id']
        
        # 检查Risk Controller字段是否已经设置
        if 'customfield_15304' in issue_data['fields'] and issue_data['fields']['customfield_15304']:
            current_value = issue_data['fields']['customfield_15304']
            if isinstance(current_value, dict) and ('name' in current_value or 'value' in current_value):
                if current_value.get('name') == 'TRD/PRD' or current_value.get('value') == 'TRD/PRD':
                    return True, "已审批"
        
        # 使用自定义的Risk Controller签核端点
        url = f"{server}/rest/shopee_risk_controller_signoff/latest/risk_controller_signoff/add"
        
        # 构建multipart/form-data格式的数据
        form_data = {
            "_charset_": "UTF-8",
            "signoff-type": "0",
            "test-result": "-1",
            "signoff-financial-risk-level": "2",
            "signoff-doc-url": risk_url,
            "signoff-comment": "",
            "signoff-id": "${report.id}",
            "id": issue_id
        }
        
        # 添加security-case字段
        security_cases = [
            "security-case-l1-1", "security-case-l2-696", "security-case-l2-697",
            "security-case-l1-2", "security-case-l2-687", "security-case-l2-698",
            "security-case-l1-3", "security-case-l2-689",
            "security-case-l1-4", "security-case-l2-700", "security-case-l2-701",
            "security-case-l1-5", "security-case-l2-690", "security-case-l2-691",
            "security-case-l2-692", "security-case-l2-693", "security-case-l2-694",
            "security-case-l2-695",
            "security-case-l1-6", "security-case-l2-683", "security-case-l2-684",
            "security-case-l2-685", "security-case-l2-686", "security-case-l2-699",
            "security-case-l1-7", "security-case-l2-688"
        ]
        
        for case in security_cases:
            form_data[case] = "no"
        
        # 使用requests的files参数构建multipart/form-data
        files = {key: (None, value) for key, value in form_data.items()}
        
        # 发送请求
        response = session.post(url, files=files)
        
        if response.status_code in [200, 201, 204]:
            return True, "审批成功"
        else:
            return False, f"审批失败: HTTP {response.status_code} - {response.text}"
            
    except Exception as e:
        return False, f"审批异常: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/process_links', methods=['POST'])
def process_links():
    """处理Jira链接并返回ticket信息"""
    data = request.get_json()
    links = data.get('links', [])
    
    # 获取Jira客户端
    jira_session = get_jira_client()
    if not jira_session:
        return jsonify({'error': '无法连接到Jira服务器'}), 500
    
    # 处理链接
    issues_info = []
    seen_links = set()
    
    for link in links:
        link = link.strip()
        if not link:
            continue
            
        issue_key = extract_issue_key(link)
        if issue_key and issue_key not in seen_links:
            seen_links.add(issue_key)
            info = get_issue_info(jira_session, issue_key)
            if info:
                issues_info.append(info)
    
    return jsonify({'issues': issues_info})

@app.route('/api/get_description', methods=['POST'])
def get_description():
    """获取ticket描述"""
    data = request.get_json()
    issue_key = data.get('issue_key')
    
    jira_session = get_jira_client()
    if not jira_session:
        return jsonify({'error': '无法连接到Jira服务器'}), 500
    
    description = get_issue_description(jira_session, issue_key)
    return jsonify({'description': description})

@app.route('/api/get_confluence_links', methods=['POST'])
def get_confluence_links():
    """获取ticket中的Confluence链接"""
    data = request.get_json()
    issue_key = data.get('issue_key')
    
    jira_session = get_jira_client()
    if not jira_session:
        return jsonify({'error': '无法连接到Jira服务器'}), 500
    
    load_dotenv()
    server = os.getenv('JIRA_SERVER')
    
    try:
        url = f"{server}/rest/api/2/issue/{issue_key}"
        response = jira_session.get(url)
        
        if response.status_code == 200:
            data = response.json()
            remarks = data['fields'].get('customfield_14500', '')  # 假设remarks字段的ID是customfield_14500
            
            # 检查Confluence链接字段
            confluence_link = data['fields'].get('customfield_11557', '')
            # 检查链接是否有效（排除空值、null、'NONE'等）
            if confluence_link and confluence_link != 'NONE' and confluence_link.strip():
                return jsonify({'confluence_links': [confluence_link]})
            
            return jsonify({'confluence_links': []})
        else:
            return jsonify({'error': '无法获取ticket信息'}), 500
            
    except Exception as e:
        return jsonify({'error': f'获取Confluence链接时发生错误: {str(e)}'}), 500

@app.route('/api/approve_issues', methods=['POST'])
def approve_issues():
    """批量审批tickets"""
    data = request.get_json()
    issues = data.get('issues', [])
    risk_urls = data.get('risk_urls', {})
    
    jira_session = get_jira_client()
    if not jira_session:
        return jsonify({'error': '无法连接到Jira服务器'}), 500
    
    results = []
    for issue in issues:
        issue_key = issue['key']
        risk_url = risk_urls.get(issue_key, '')
        
        success, message = approve_issue(jira_session, issue_key, risk_url)
        results.append({
            'key': issue_key,
            'success': success,
            'message': message
        })
    
    return jsonify({'results': results})

if __name__ == '__main__':
    # 云端/本地自适应端口与模式
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') == 'development'
    is_cloud = os.environ.get('PORT') is not None

    print("🌐 Jira审批工具启动中...")
    if is_cloud:
        print(f" 云端部署模式 - 端口: {port}")
    else:
        print("📱 手机访问地址: http://10.38.104.191:5001")
        print("💻 电脑访问地址: http://localhost:5001")
    print("按 Ctrl+C 停止应用")
    print("-" * 50)
    app.run(debug=debug, host='0.0.0.0', port=port)