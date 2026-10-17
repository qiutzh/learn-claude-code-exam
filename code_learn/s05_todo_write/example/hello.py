def greet(name: str) -> None:
    """向指定名字的人打印一句问候语。

    参数：
        name: 要问候的名字。
    """
    message = f"Hello, {name}"
    print(message)


if __name__ == "__main__":
    greet("Claude")
