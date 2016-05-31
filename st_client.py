from __future__ import print_function
from pprint import pprint

import requests_toolbelt
import os
import requests
import st_exceptions
import st_auth
import urlparse
import json

__author__ = 'vsitzmann'

class ScitranClient(object):
    '''Handles api calls to a certain instance.

    Attributes:
        instance (str): instance name.
        base_url (str): The base url of that instance, as returned by stAuth.create_token(instance, st_dir)
        token (str): Authentication token.
        st_dir (str): The path to the directory where token and authentication file are kept for this instance.
    '''

    def __init__(self,
                 instance_name,
                 st_dir,
                 debug=False,
                 downloads_dir='downloads',
                 gear_in_dir='downloads/input',
                 gear_out_dir='downloads/output'):

        self.session = requests.Session()
        self.instance = instance_name
        self.st_dir = st_dir
        self._authenticate()
        self.debug = debug
        self.downloads_dir = downloads_dir
        self.gear_in_dir = gear_in_dir
        self.gear_out_dir = gear_out_dir

        self._set_up_dir_structure()

        if self.debug:
            self.session.hooks = dict(response=self._print_request_info)

    def _set_up_dir_structure(self):
        if not os.path.isdir(self.downloads_dir):
            os.mkdir(self.downloads_dir)
        if not os.path.isdir(self.gear_in_dir):
            os.mkdir(self.gear_in_dir)
        if not os.path.isdir(self.gear_out_dir):
            os.mkdir(self.gear_out_dir)

    def _check_status_code(self, response):
        '''Checks the status codes of received responses and raises errors in case of bad http requests.'''
        status_code = response.status_code

        if status_code == 200:
            return

        exceptions_dict = {
            403: st_exceptions.NoPermission,
            404: st_exceptions.NotFound,
            400: st_exceptions.WrongFormat,
            500: st_exceptions.BadRequest
        }

        exception = exceptions_dict.get(status_code)

        if exception:
            raise exception(response.text)

    def _url(self, path):
        '''Assembles a url from this classes's base_url and the given path.

        Args:
            path (str): path part of the URL.

        Returns:
            string: The full URL.
        '''
        return urlparse.urljoin(self.base_url, path)

    def _print_request_info(self, response, *args, **kwargs):
        '''Prints information about requests for debugging purposes.
        '''
        prepared_request = response.request

        print("\nRequest dump:\n")

        pprint(prepared_request.method)
        pprint(prepared_request.url)
        pprint(prepared_request.headers)
        pprint(prepared_request.body)

        print('\n')

    def _authenticate_request(self, request):
        '''Automatically appends the authorization token to every request sent out.'''
        if self.token:
            request.headers.update({
                'Authorization':self.token
            })

            return request
        else:
            raise st_exceptions.InvalidToken('Not Authenticated!')

    def search_anything_should_joined(self, path='', file_props={}, acq_props={}, collection_props={}, session_props={}, project_props={}):
        constraints = {}

        if file_props:
            constraints.update(self._bool_match_multiple_field('files', file_props))

        if acq_props:
            constraints.update(self._bool_match_multiple_field('acquisitions', acq_props))

        if collection_props:
            constraints.update(self._bool_match_multiple_field('collections', collection_props))

        if session_props:
            constraints.update(self._bool_match_multiple_field('sessions', session_props))

        if project_props:
            constraints.update(self._bool_match_multiple_field('sessions', project_props))

        return self.search(path, constraints)[os.path.basename(path)]

    def _authenticate(self):
        self.token, self.base_url = st_auth.create_token(self.instance, self.st_dir)
        self.base_url = urlparse.urljoin(self.base_url, 'api/')

    def _request(self, endpoint, method='GET', params=None, data=None, headers=None, files=None):
        '''Dispatches requests, taking care of the instance-specific base_url and authentication. Also raises appropriate HTTP errors.
        Args:
            method (str): The HTTP method to perform ('GET', 'POST'...)
            params (dict): Dict of http parameters.
            data (str): Data payload that should be sent with the request.
            headers (dict): Dict of http headers.

        Returns:
            The full server response.

        Raises:
            http code 403: st_exceptions.NoPermission,
            http code 404: st_exceptions.NotFound
            no token available: st_exceptions.InvalidToken
        '''
        response = self.session.request(url=self._url(endpoint),
                                        method=method,
                                        params=params,
                                        data=data,
                                        headers=headers,
                                        auth=self._authenticate_request,
                                        files=files)

        self._check_status_code(response)
        return response

    def search(self, path, constraints, num_results=-1):
        '''Searches remote "path" objects with constraints.

        This is the most general function for an elastic search that allows to pass in a "path" as well as
        a user-assembled list of constraints.

        Args:
            path (string): The path that should be searched, i.e. 'acquisitions/files'
            constraints (dict): The constraints of the search, i.e. {'collections':{'should':[{'match':...}, ...]}, 'sessions':{'should':[{'match':...}, ...]}}

        Returns:
            python dict of search results.
        '''
        search_body = {
            'path':path
        }

        search_body.update(constraints)

        if num_results != -1:
            search_body.update({'size':num_results})

        response = self._request(endpoint="search", data=json.dumps(search_body), params={'size':num_results})

        return json.loads(response.text)

    def search_files(self, constraints, num_results=-1):
        return self.search(path='files', constraints=constraints, num_results=num_results)['files']

    def search_collections(self, constraints, num_results=-1):
        return self.search(path='collections', constraints=constraints, num_results=num_results)['collections']

    def search_sessions(self, constraints, num_results=-1):
        return self.search(path='sessions', constraints=constraints, num_results=num_results)['sessions']

    def search_projects(self, constraints, num_results=-1):
        return self.search(path='projects', constraints=constraints, num_results=num_results)['projects']

    def search_acquisitions(self, constraints, num_results=-1):
        return self.search(path='acquisitions', constraints=constraints, num_results=num_results)['acquisitions']

    def _bool_match_single_field(self, element, field_name, matching_strings, bool_type='should'):
        ''' Assembles the common elasticsearch-query of specifieng several possible values for a single field.
        '''
        result = {
            element:{
                'constant_score':{
                    'query':{
                        'bool':{
                            bool_type: [ {'match':{field_name:matching_string}} for matching_string in matching_strings ]
                        }
                    }
                }
            }
        }

        return result

    def _bool_match_multiple_field(self, element, field_value_dict, bool_type='should'):
        ''' Assembles the common elasticsearch-query of wanting to specify several field-value pairs for a certain element.
        '''
        constraints_list = []
        for field, value in field_value_dict.iteritems():
            if isinstance(value, list):
                constraints_list.extend([{'match':{field:single_value}} for single_value in value])
            else:
                constraints_list.append({'match':{field:value}})

        result = {
            element:{
                'constant_score':{
                    'query':{
                        'bool':{
                            bool_type:constraints_list
                        }
                    }
                }
            }
        }

        return result

    def download_file(self, container_type, container_id, file_name, dest_dir=None):
        '''Download a file that resides in a specified container.

        Args:
            container_type (str): The type of container the file resides in (i.e. acquisition, session...)
            container_id (str): The elasticsearch id of the specific container the file resides in.
            dest_dir (str): Path to where the acquisition should be downloaded to.
            file_name (str): Name of the file.

        Returns:
            string. The absolute file path to the downloaded acquisition.
        '''
        # If no destination directory is given, default to the gear_in_dir of the object.
        if not dest_dir:
            dest_dir = self.gear_in_dir

        endpoint = "%s/%s/files/%s"%(container_type, container_id, file_name)
        abs_file_path = os.path.join(dest_dir, file_name)

        response = self._request(endpoint=endpoint, method='GET')

        with open(abs_file_path, 'wb') as fd:
            for chunk in response.iter_content():
                fd.write(chunk)

        return abs_file_path

    def download_all_file_search_results(self, file_search_results, dest_dir):
        '''Download all files contained in the list returned by a call to ScitranClient.search_files()

        Args:
            file_search_results (dict): Search result.
            dest_dir (str): Path to the directory that files should be downloaded to.

        Returns:
            string: Destination directory.
        '''
        for file_search_result in file_search_results:
            container_id = file_search_result['_source']['container_id']
            container_name = file_search_result['_source']['container_name']
            file_name = file_search_result['_source']['name']
            self.download_file(container_name, container_id, file_name, dest_dir=dest_dir)

        return dest_dir

    def upload_analysis(self, in_file_path, out_file_path, metadata, target_collection_id):
        '''Attaches an input file and an output file to a collection on the remote end.

        Args:
            in_file_path (str): The path to the input file.
            out_file_path (str): The path to the output file.
            metadata (dict): A dictionary with metadata.
            target_collection_id (str): The id of the collection the file will be attached to.

        Returns:
            requests Request object of the POST request.
        '''
        endpoint = "collections/%s/analyses"%(target_collection_id)

        in_filename= os.path.split(in_file_path)[1]
        out_filename = os.path.split(out_file_path)[1]

        # If metadata doesn't contain it yet, add the output and the input file names.
        metadata.update({
            'outputs':[{'name':out_filename}],
            'inputs':[{'name':in_filename}]
        })

        # payload = {
        #    'metadata':json.dumps(metadata)
        # }
        #
        # files = {'file1':open(in_file_path, 'rb'), 'file2':open(out_file_path, 'rb')}
        #
        # response = self._request(method='POST', endpoint=endpoint, data=payload, files = files)

        # with open(in_filename, 'rb') as in_file, open(out_filename) as out_file:
        with open(in_filename, 'rb') as in_file, open(out_filename, 'rb') as out_file:
            mpe = requests_toolbelt.multipart.encoder.MultipartEncoder(
                fields={'metadata': json.dumps(metadata), 'file1': (in_filename, in_file), 'file2':(out_filename, out_file)}
            )
            response = self._request(endpoint, method='POST', data=mpe, headers={'Content-Type':mpe.content_type})

        return response

    def submit_job(self,
                   inputs,
                   destination,
                   tags=[]):
        '''Submits a job to the flywheel factory

        Args:
            inputs (dict):
            destination (dict):

        '''
        # submit_job_command = sprintf(
            # 'curl -k -X POST %s/%s -d ''%s'' -H "X-SciTran-Auth:%s" -H "X-SciTran-Name:live.sh" -H "X-SciTran-Method:script" ',
            # st.url, endpoint, job_body, drone_secret);

        endpoint = 'jobs/add'

        job_dict = {}
        job_dict.update({'inputs':inputs})
        job_dict.update({'tags':tags})
        job_dict.update({'destination':destination})

        response = self._request(endpoint=endpoint,
                                 data=json.dumps(job_dict),
                                 headers={'X-SciTran-Name:live.sh', 'X-SciTran-Method:script'})
        return response

    def run_gear_and_upload_analysis(self, container, in_dir=None, out_dir=None, in_file=None, out_file=None):
        if not in_dir:
            in_dir = self.gear_in_dir
        if not out_dir:
            out_dir = self.gear_out_dir

        # Check if the output directory is empty.
        if os.listdir(out_dir):
            print("Output directory is not empty!")
            return

        pass




