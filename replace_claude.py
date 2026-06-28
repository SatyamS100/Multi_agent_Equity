import os
import re

directory = '.'

replacements = {
    "LLM": "LLM",
    "llm": "llm",
    "LLM": "LLM",
    "ChatGroq": "ChatGroq",
    "langchain_groq": "langchain_groq",
    "GROQ_API_KEY": "GROQ_API_KEY",
    "llm-sonnet-4-6": "llama3-70b-8192",
    "Groq": "Groq"
}

for root, dirs, files in os.walk(directory):
    if '.git' in root:
        continue
    for file in files:
        if file.endswith('.py') or file == 'requirements.txt':
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            new_content = content
            # Special case for anthropic package in requirements.txt
            if file == 'requirements.txt':
                new_content = re.sub(r'langchain-anthropic==[0-9\.]+', 'langchain-groq==0.1.0', new_content)
                new_content = re.sub(r'anthropic==[0-9\.]+', 'groq==0.5.0', new_content)
            else:
                for k, v in replacements.items():
                    new_content = new_content.replace(k, v)
                
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Updated {filepath}")
