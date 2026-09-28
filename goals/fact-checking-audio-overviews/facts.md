# Facts

- The system transcribes the generated Audio Overview from an audio format into a text transcript.
- The system applies the SIFT protocol to the transcript, executing an external web search to fact-check claims made in the audio overview.
- The system builds speaker profiles for the two hosts, tracking shifts in tenor and modality between them during the conversation.
- The system detects and flags semantic anomalies where host banter drifts or hallucinated claims appear.
- The system generates a detailed Markdown report summarizing the findings, including inline citations to external sources and data quality warnings.
