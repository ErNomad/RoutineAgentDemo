from agent import Agent, Agent1, Agent2, Agent3


if __name__ == "__main__":
    agent3 = Agent3()
    agent2 = Agent2(agent3)
    agent1 = Agent1(agent2)
    agents = [agent1, agent2, agent3]

    for a in agents:
        a.start()  # all agents are now listening

    print('Type "Good morning" or "Good night" (or "quit" to exit).')
    try:
        while True:
            text = input("> ").strip()
            if text.lower() == "quit":
                break
            if text:
                agent1.send(text)
    except (EOFError, KeyboardInterrupt):
        pass

    # Stop agents in order so queued messages are processed first.
    for a in agents:
        a.stop()
        a.join()