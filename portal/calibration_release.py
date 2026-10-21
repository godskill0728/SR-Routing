"""Bounded retention for a twenty-condition calibration; scheduling unchanged."""
import inspect
import axes_release as previous

portal=previous.portal
original_pages=previous.pages
race=previous.previous.previous.parallel.race
source=inspect.getsource(race.start_job)
assert source.count('if len(batch.JOBS) >= 8:')==1
source=source.replace('if len(batch.JOBS) >= 8:', 'if len(batch.JOBS) >= 32:')
exec(compile(source,'<bounded-retention-32>','exec'),race.__dict__)
pages=original_pages

if __name__=='__main__':portal.main()