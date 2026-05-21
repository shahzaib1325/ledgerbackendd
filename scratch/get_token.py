import requests, json
url = 'http://localhost:8000/api/v1/auth/login'
payload = {"email": "admin@example.com", "password": "SecurePass1"}
headers = {'Content-Type': 'application/json'}
resp = requests.post(url, json=payload, headers=headers)
print('Status:', resp.status_code)
print('Response:', resp.text)
if resp.ok:
    data = resp.json()
    token = data.get('data', {}).get('access_token')
    print('Token:', token)
