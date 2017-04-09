import datetime
import random

import requests

from app import db
from app.spider.model import SpiderStatus, JobExecution, JobInstance, Project, SpiderInstance, JobPriority


class SpiderServiceProxy():
    def __init__(self, service_id):
        # service machine id
        self._service_id = service_id

    def get_project_list(self):
        '''

        :return: []
        '''
        pass

    def get_spider_list(self, *args, **kwargs):
        '''

        :param args:
        :param kwargs:
        :return: []
        '''
        return NotImplementedError

    def get_daemon_status(self):
        return NotImplementedError

    def get_job_list(self, project_name, spider_status):
        '''

        :param project_name:
        :param spider_status:
        :return: job service execution id list
        '''
        return NotImplementedError

    def start_spider(self, *args, **kwargs):
        '''

        :param args:
        :param kwargs:
        :return: {id:foo,start_time:None,end_time:None}
        '''
        return NotImplementedError

    def cancel_spider(self, *args, **kwargs):
        return NotImplementedError

    def deploy(self, *args, **kwargs):
        pass

    @property
    def service_id(self):
        return self._service_id


class SpiderAgent():
    def __init__(self):
        self.spider_service_instances = []

    def regist(self, spider_service_proxy):
        if isinstance(spider_service_proxy, SpiderServiceProxy):
            self.spider_service_instances.append(spider_service_proxy)

    def get_project_list(self):
        project_list = self.spider_service_instances[0].get_project_list()
        Project.load_project(project_list)
        return [project.to_dict() for project in Project.query.all()]

    def get_spider_list(self, project):
        spider_instance_list = self.spider_service_instances[0].get_spider_list(project.project_name)
        for spider_instance in spider_instance_list:
            spider_instance.project_id = project.id
        SpiderInstance.load_spider(spider_instance_list)
        return [spider.to_dict() for spider in SpiderInstance.query.filter_by(project_id=project.id).all()]

    def get_daemon_status(self):
        pass

    def sync_job_status(self, project):
        for spider_service_instance in self.spider_service_instances:
            # running
            for job_execution_dict in spider_service_instance.get_job_list(project.project_name, SpiderStatus.RUNNING):
                job_execution = JobExecution.find_job_execution_by_service_job_execution_id(job_execution_dict['id'])
                if job_execution and job_execution.running_status == SpiderStatus.PENDING:
                    job_execution.start_time = job_execution_dict['start_time']
                    job_execution.running_status = SpiderStatus.RUNNING
                    job_execution.running_on = spider_service_instance.service_id
                    db.session.commit()

            # finished
            for job_execution_dict in spider_service_instance.get_job_list(project.project_name, SpiderStatus.FINISHED):
                job_execution = JobExecution.find_job_execution_by_service_job_execution_id(job_execution_dict['id'])
                if job_execution and job_execution.running_status == SpiderStatus.RUNNING:
                    job_execution.running_status = SpiderStatus.FINISHED
                    job_execution.end_time = job_execution_dict['end_time']
                    db.session.commit()

    def get_job_status(self, project):
        result = {"PENDING": [], "RUNNING": [], "FINISHED": [], "CANCELED": []}
        for jobExecution in JobExecution.query.filter(JobExecution.running_status != SpiderStatus.FINISHED,
                                                      JobExecution.running_status != SpiderStatus.CANCELED,
                                                      JobExecution.project_id == project.id).all():
            if jobExecution.running_status == SpiderStatus.PENDING:
                result['PENDING'].append(jobExecution.to_dict())
            if jobExecution.running_status == SpiderStatus.RUNNING:
                result['RUNNING'].append(jobExecution.to_dict())
        for jobExecution in JobExecution.query.filter(JobExecution.running_status == SpiderStatus.FINISHED,
                                                      JobExecution.project_id == project.id).limit(100):
            result['FINISHED'].append(jobExecution.to_dict())
        return result

    def start_spider(self, job_instance):
        project = Project.find_project_by_id(job_instance.project_id)
        spider_name = job_instance.spider_name
        arguments = {}
        if job_instance.spider_arguments:
            arguments = dict(map(lambda x: x.split("="), job_instance.spider_arguments.split(",")))
        threshold = 0
        daemon_size = len(self.spider_service_instances)
        if job_instance.priority == JobPriority.HIGH:
            threshold = int(daemon_size / 2)
        if job_instance.priority == JobPriority.HIGHEST:
            threshold = int(daemon_size)
        threshold = 1 if threshold == 0 else threshold
        candidates = self.spider_service_instances
        leaders = []
        # TODO optimize some better func to vote the leader
        for i in range(threshold):
            leaders.append(random.choice(candidates))
        for leader in leaders:
            serviec_job_id = leader.start_spider(project.project_name, spider_name, arguments)
            job_execution = JobExecution()
            job_execution.project_id = job_instance.project_id
            job_execution.service_job_execution_id = serviec_job_id
            job_execution.job_instance_id = job_instance.id
            job_execution.create_time = datetime.datetime.now()
            job_execution.running_on = leader.service_id
            db.session.add(job_execution)
            db.session.commit()

    def cancel_spider(self, job_execution):
        job_instance = JobInstance.find_job_instance_by_id(job_execution.job_instance_id)
        project = Project.find_project_by_id(job_instance.project_id)
        for spider_service_instance in self.spider_service_instances:
            if spider_service_instance.service_id == job_execution.running_on:
                if spider_service_instance.cancel_spider(project.project_name, job_execution.service_job_execution_id):
                    job_execution.running_status = SpiderStatus.CANCELED
                    db.session.commit()
                break

    def deploy(self, project, file_path):
        for spider_service_instance in self.spider_service_instances:
            if not spider_service_instance.deploy(project.project_name, file_path):
                return False
        return True


if __name__ == '__main__':
    pass
