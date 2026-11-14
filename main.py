from ai import chat
from config import MODEL


print("now_model:",MODEL)

question = input("enter your question:")
answer = chat(question)
print("answer:",answer)
