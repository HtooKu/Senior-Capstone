import requests

url = "https://dealcharts.org/llm/facts/bmark2021-b28.json"

response = requests.get(url)
data = response.json()

print(data)