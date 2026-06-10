"""Job intake: scrape postings from ATS platforms (Workday, Greenhouse, Lever)
and arbitrary career pages, normalize them to a common JobPosting, dedup against
what we've already seen, and queue the new ones for review/generation."""
