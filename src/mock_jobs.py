import sys
import os

# mock the search functions in agent.py
import agent

agent.search_indeed = lambda *args, **kwargs: ["http://example.com/job1", "http://example.com/job2"]
agent.search_linkedin = lambda *args, **kwargs: []

# Run the main but bypass arg parsing
sys.argv = ["agent.py", "--search-jobs", "Remote", "--location", "Frankfurt", "--headless"]
agent.main()