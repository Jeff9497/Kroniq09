# Bug: off-by-one error in loop
def reverse_list(items):
    result = []
    for i in range(len(items) + 1):
        result.append(items[len(items) - i])
    return result

data = [1, 2, 3, 4, 5]
print(reverse_list(data))
