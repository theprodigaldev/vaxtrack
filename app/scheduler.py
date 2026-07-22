from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine
from app.notifications import send_reminders

# Module-level reference set by init_scheduler. APScheduler pickles job functions
# and their arguments when using a persistent job store, so the Flask app object
# must NOT appear in args (it contains lambdas and is not picklable). Instead we
# hold the app here and pass only the plain string job_type as the pickled argument.
_app = None


def _run_reminders(job_type):
    """Thin module-level wrapper so APScheduler only needs to pickle a string."""
    send_reminders(_app, job_type)


def init_scheduler(app):
    """Initialize APScheduler with 3 notification jobs (WAT = UTC+1).

    IMPORTANT: This app must run as a SINGLE App Service instance. If scaled out
    to multiple instances, each would independently fire the same reminder jobs,
    causing duplicate SMS/email sends. Move the scheduler to a separate process
    (e.g., Azure Container App or a dedicated worker) before enabling scale-out.
    """
    global _app
    _app = app

    # Persist jobs in MySQL so they survive App Service restarts. replace_existing=True
    # on each add_job call updates the stored job definition without creating duplicates,
    # so re-running create_app() after a restart is safe.
    #
    # APScheduler creates its own SQLAlchemy engine from the raw URL, so
    # SQLALCHEMY_ENGINE_OPTIONS (pool_recycle, SSL, etc.) does NOT flow through
    # automatically. We build an engine here using the same options so the job
    # store connection behaves identically to Flask-SQLAlchemy's connection.
    _engine_opts = {'pool_recycle': 280, 'pool_pre_ping': True}
    _connect_args = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}).get('connect_args')
    if _connect_args:
        _engine_opts['connect_args'] = _connect_args
    _scheduler_engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], **_engine_opts)
    jobstores = {
        'default': SQLAlchemyJobStore(engine=_scheduler_engine)
    }
    scheduler = BackgroundScheduler(jobstores=jobstores, daemon=True)

    # Job 1: Evening before 18:00 WAT (17:00 UTC)
    scheduler.add_job(
        func=_run_reminders,
        trigger='cron',
        hour=17, minute=0,
        args=['evening_before'],
        id='evening_reminder',
        name='Evening reminder (18:00 WAT)',
        replace_existing=True
    )

    # Job 2: Morning of 06:00 WAT (05:00 UTC)
    scheduler.add_job(
        func=_run_reminders,
        trigger='cron',
        hour=5, minute=0,
        args=['morning_of'],
        id='morning_reminder',
        name='Morning reminder (06:00 WAT)',
        replace_existing=True
    )

    # Job 3: Noon follow-up 12:00 WAT (11:00 UTC)
    scheduler.add_job(
        func=_run_reminders,
        trigger='cron',
        hour=11, minute=0,
        args=['noon_followup'],
        id='noon_followup',
        name='Noon follow-up (12:00 WAT)',
        replace_existing=True
    )

    scheduler.start()
    app.scheduler = scheduler
