# Bug: string + int without conversion
def build_greeting(name, age):
    return "Hello " + name + ", you are " + age + " years old."

print(build_greeting("Jeff", 25))
