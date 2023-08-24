import openai
import os
import torch
from typing import Union, List, Any, Dict
import commune as c
import json
# class OpenAILLM(c.Module):


class OpenAILLM(c.Module):
    
    prompt = """{x}"""

    whitelist = ['forward', 'chat', 'ask']
    
    def __init__(self, 
                 config: Union[str, Dict[str, Any], None] = None,
                 **kwargs
                ):

        config = self.set_config(config, kwargs=kwargs)
        self.set_tag(config.tag)
        self.set_api_key(config.api_key)
        self.set_prompt(config.get('prompt', self.prompt))
        self.set_tokenizer(config.tokenizer)
        
        
        # self.params  = dict(
        #          model =self.config.model,
        #         temperature=self.config.temperature,
        #         max_tokens=self.config.max_tokens,
        #         top_p=self.config.top_p,
        #         frequency_penalty=self.config.frequency_penalty,
        #         presence_penalty=self.config.presence_penalty,
        # )
    
        
    def resolve_api_key(self, api_key:str = None) -> str:
        api_key = os.environ.get(api_key, api_key)
        assert isinstance(api_key, str),f"API Key must be a string,{api_key}"
        self.api_key = self.config.api_key =  api_key
        return api_key

    hour_limit_count = {}
    def ensure_token_limit(self, input:str , output:str ):
        text = input + output
        tokens = self.tokenizer(text)['input_ids']
        hour = c.time() // 3600
        if hour not in self.hour_limit_count:
            self.hour_limit_count[hour] = 0


    @classmethod
    def random_api_key(cls):
        valid_api_keys = cls.api_keys()
        assert len(valid_api_keys) > 0, "No valid API keys found, please add one via ```c openai add_api_key <api_key>```"
        return valid_api_keys[0]
  
    def set_api_key(self, api_key: str = None) -> str:
        api_key = api_key or self.config.api_key
        self.api_key = self.resolve_api_key(api_key)
        openai.api_key = self.api_key
        return {'msg': f"API Key set to {openai.api_key}", 'success': True}

    def resolve_prompt(self, *args, prompt = None, **kwargs):
        if prompt == None:
            prompt = self.prompt
            prompt_variables  = self.prompt_variables
        else:
            assert isinstance(prompt, str)
            prompt_variables = self.get_prompt_variables(prompt)
        
                    
        if len(args) > 0 :
            assert len(args) == len(prompt_variables), f"Number of arguments must match number of prompt variables: {self.prompt_variables}"
            kwargs = dict(zip(prompt_variables, args))

        for var in prompt_variables:
            assert var in kwargs

        prompt = prompt.format(**kwargs)
        return prompt
    
    

    def is_error(self, response):
        return 'error' in response

    def is_success(self, response):
        return not self.is_error(response)

    def call(self, text):
        return self.forward(text, role='user')
        

    
    def forward(self,prompt:str = 'sup?',
                model:str = 'gpt-3.5-turbo',
                presence_penalty:float = 0.0, 
                frequency_penalty:float = 0.0,
                temperature:float = 0.9, 
                max_tokens:int = 100, 
                top_p:float = 1,
                choice_idx:int = 0,
                api_key:str = None,
                retry: bool = True,
                role:str = 'user',
                history: list = None,
                **kwargs) -> str:
        t = c.time()
        if not model in self.config.models:
            f"Model must be one of {self.config.models}"
            
        
        openai.api_key = api_key or self.api_key

        params = dict(
                    model = model,
                    presence_penalty = presence_penalty, 
                    frequency_penalty = frequency_penalty,
                    temperature = temperature, 
                    max_tokens = max_tokens, 
                    top_p = top_p
                    )
        
        messages = [{"role": role, "content": prompt}]
        if history:
            messages = history + messages

        try:
            
            response = openai.ChatCompletion.create(messages=messages, **params)
        except Exception as e:
            # if we get an error, try again with a new api key that is in the whitelist
            if retry:
                self.set_api_key(self.random_api_key())
                response = openai.ChatCompletion.create(messages=messages, **params)

            else:
                response = c.detailed_error(e)
                return response
                
        output_text = response = response['choices'][choice_idx]['message']['content']
        input_tokens = self.num_tokens(prompt)
        output_tokens = self.num_tokens(output_text)
        latency = c.time() - t

        stats = {
            'prompt': prompt,
            'response': output_text,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'latency': latency,
            'history': history,
            'timestamp': t,
        }

        # self.add_stats(tag=t, stats=stats)

        return output_text


    _stats = None
    _stats_update_time = 0
    @classmethod
    def stats(cls, skip_keys = ['prompt', 'response', 'history'], refresh_interval=5):
        if cls._stats != None or c.time() % refresh_interval > (c.time() - cls._stats_update_time):
            stat_paths = cls.ls('stats')
            cls._stats = [cls.get(path) for path in stat_paths]
            cls._stats_update_time = c.time()
        if cls._stats == None:
            cls._stats = stats
        stats = [{k:v for k,v in cls.get(path).items() if k not in skip_keys} for path in stat_paths]

        return  stats
    @classmethod
    def tokens_per_hour(self):
        return self.tokens_per_period(period=3600)
    @classmethod
    def tokens_per_period(cls, period=3600):
        stats = cls.stats()
        one_hour_ago = c.time() - period
        stats = [s for s in stats if s['timestamp'] > one_hour_ago]
        tokens_per_hour = sum([s['input_tokens'] + s['output_tokens'] for s in stats])
        return tokens_per_hour

    def add_stats(self, tag:str, stats:dict,  ):
        self.put(f'stats/{tag}.json', stats)
        saved_stats_paths = self.ls('stats')
        if len(saved_stats_paths) > self.config.max_stats:
            # remove the oldest stat
            sorted(saved_stats_paths, key=lambda x: int(x.split('.')[0]))
            self.rm(saved_stats_paths[0])

        return {'msg': f"Saved stats for {tag}", 'success': True}

    generate = call = forward


    def resolve_params(self, params = None):
        if params == None:
            params = {}
        params = c.locals2kwargs(params)
        output_params = {}
        for p in self.params:
            if p in  self.params:
                if params.get(p) == None:
                    output_params[p] = self.params[p]
                else:
                    assert isinstance(params[p], type(self.params[p])), f"Parameter {p} must be of type {type(self.params[p])}, not {type(params[p])}"
                    output_params[p] = params[p]
            
        return output_params


        
        
        
    @classmethod
    def chat(cls, *args, **kwargs):
        return cls().forward(*args, **kwargs)
        
    @property
    def history(self):
        return self.config.get('history', [])
    @history.setter
    def history(self, history):
        self.config['history'] = history

    def set_prompt(self, prompt: str):
        
        if prompt == None:
            prompt = self.prompt
        self.prompt = prompt
        assert isinstance(self.prompt, str), "Prompt must be a string"
        self.prompt_variables = self.get_prompt_variables(self.prompt)
    @staticmethod   
    def get_prompt_variables(prompt):
        variables = []
        tokens = prompt.split('{')
        for token in tokens:
            if '}' in token:
                variables.append(token.split('}')[0])
        return variables


    api_key_path = 'api_keys'

    @classmethod
    def add_api_key(cls, api_key, k=api_key_path):
        api_keys = cls.get(k, [])
        c.print(api_keys)
        if api_key in api_keys:
            return {'error': f'api_key {api_key} already added'}
        verified = cls.verify_api_key(api_key)
        if not verified:
            return {'error': f'api_key {api_key} not verified'}
        api_keys.append(api_key)
        api_keys = list(set(api_keys))
        cls.put(k, api_keys)
        assert api_key in cls.api_keys(), f"API key {api_key} not added"
        return {'msg': f'added api_key {api_key}'}


    @classmethod
    def add_api_keys(cls, *keys):
        for k in keys:
            cls.add_api_key(k)


    @classmethod
    def set_api_keys(cls, api_keys: List[str], k: str=api_key_path):
        assert isinstance(api_keys, list)
        cls.put(k, api_keys)
        return {'msg': f'added api_key {api_keys}'}

    @classmethod
    def rm_api_key(cls, api_key, k=api_key_path):

        api_keys = cls.get('api_keys', [])
        if api_key not in api_keys:
            return {'error': f'api_key {api_key} not found', 'api_keys': api_keys}

        api_idx = None
        for i, api_k in enumerate(api_keys):
            if api_key != api_k:
                api_idx = i
        if api_idx == None:
            return {'error': f'api_key {api_key} not found', 'api_keys': api_keys}

        del api_keys[api_idx]
        cls.set_api_keys(api_keys)

        return {'msg': f'removed api_key {api_key}', 'api_keys': api_keys}

    @classmethod
    def update(cls):
        cls.set_api_keys(cls.valid_api_keys())
    
    @classmethod
    def valid_api_key(self):
        return self.valid_api_keys()[0]
    @classmethod
    def valid_api_keys(cls, verbose:bool = True):
        api_keys = cls.api_keys()
        valid_api_keys = []
        for api_key in api_keys:
            if verbose:
                c.print(f'Verifying API key: {api_key}', color='blue')
            if cls.verify_api_key(api_key):
                valid_api_keys.append(api_key)
        
        valid_api_keys = c.shuffle(valid_api_keys)
        return valid_api_keys
    valid_keys = verify_api_keys = valid_api_keys

    @classmethod
    def api_keys(cls, update:bool = False):
        if update:
            cls.put('api_keys', self.valid_api_keys())
        return cls.get('api_keys', [])
        
    def num_tokens(self, text:str) -> int:
        num_tokens = 0
        tokens = self.tokenizer.encode(text)
        if isinstance(tokens, list) and isinstance(tokens[0], list):
            for i, token in enumerate(tokens):
                num_tokens += len(token)
        else:
            num_tokens = len(tokens)
        return num_tokens
    @classmethod
    def test(cls, input:str = 'What is the meaning of life?',**kwargs):
        module = cls()
        c.print(module.ask(input))

    
    @classmethod
    def verify_api_key(cls, api_key:str, text:str='ping'):
        model = cls(api_key=api_key)
        output = model.forward(text, max_tokens=1, api_key=api_key, retry=False)
        if 'error' in output:
            c.print(f'ERROR \u2717 -> {api_key}', output['error'], color='red')
            return False
        else:
            # checkmark = u'\u2713'
            c.print(f'Verified \u2713 -> {api_key} ', output, color='green')
        return True

    @classmethod
    def restart_miners(cls, *args,**kwargs):
        for m in cls.miners(*args, **kwargs):
            c.restart(m)
         
    def set_tokenizer(self, tokenizer: str):

        if tokenizer == None and hasattr(self, 'tokenizer'):
            return self.tokenizer
             
        if tokenizer == None:
            tokenizer = 'gpt2'
        from transformers import AutoTokenizer

        if isinstance(tokenizer, str):
            try:
                tokenizer = AutoTokenizer.from_pretrained(tokenizer, use_fast= True)
            except ValueError:
                print('resorting ot use_fast = False')
                tokenizer = AutoTokenizer.from_pretrained(tokenizer, use_fast=False)
        
        tokenizer.pad_token = tokenizer.eos_token 
            
        self.tokenizer = tokenizer
    
        return self.tokenizer

    
    
    
    def decode_tokens(self,input_ids: Union[torch.Tensor, List[int]], **kwargs) -> Union[str, List[str], torch.Tensor]:
        return self.tokenizer.decode(input_ids, **kwargs)
    def encode_tokens(self, 
                 text: Union[str, List[str], torch.Tensor], 
                 return_tensors='pt', 
                 padding=True, 
                 truncation=True, 
                 max_length=256,
                 **kwargs):
        
        return self.tokenizer(text, 
                         return_tensors=return_tensors, 
                         padding=padding, 
                         truncation=truncation, 
                         max_length=max_length)
    # @classmethod
    # def serve(cls, *args, **kwargs):
    #     name = cls.name()


    @classmethod
    def validate(cls, text = 'What is the meaning of life?', max_tokens=10):
        prefix = cls.module_path()
        jobs = []
        servers = c.servers(prefix)
        for s in servers:
            job = c.call(module=s, 
                         fn='forward', 
                         text=text, 
                         temperature=0.0,
                         max_tokens=max_tokens,
                        return_future=True
                        )
            jobs.append(job)
        assert len(jobs) > 0, f'No servers found with prefix {prefix}'
        results = c.gather(jobs)
        response = {}
        for s, result in zip(c.servers(prefix), results):
            response[s] = result

        return response




 
    @classmethod     
    def st(cls):
        import streamlit as st
        model = cls()
        
        buttons = {}
        st.write(c.python2types(model.__dict__))
        response = 'bro what is up?'
        prompt = '''
        {x}
        Document this in a markdown format that i can copy
        '''
        
        
        st.write(model.forward(model.fn2str()['forward'], prompt=prompt, max_tokens=1000))
        
        
        
        # for i in range(10):
        #     response = model.forward(prompt='What is the meaning of life?', max_tokens=1000)
        #     st.write(response, model.stats)
        # st.write(model.forward(prompt='What is the meaning of life?'))
        # model.save()
        # model.test()
        # st.write('fuckkkkffffff')

